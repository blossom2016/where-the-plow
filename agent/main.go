package main

import (
	"bufio"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"math"
	"math/rand"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"

	"github.com/kardianos/service"
)

// errorBody builds a JSON {"error": "..."} payload with proper escaping.
func errorBody(err error) []byte {
	b, _ := json.Marshal(map[string]string{"error": err.Error()})
	return b
}

var version = "dev"

const (
	// After this many consecutive fetch failures, enter hibernate mode.
	hibernateThreshold = 30
	// Maximum backoff duration before hibernate kicks in.
	maxBackoff = 10 * time.Minute
	// How often to checkin while hibernating.
	hibernateCheckinInterval = 10 * time.Minute
)

// backoffDuration returns exponential backoff capped at maxBackoff.
// Formula: min(base * 2^failures, maxBackoff) with ±10% jitter.
func backoffDuration(baseInterval time.Duration, consecutiveFailures int) time.Duration {
	exp := math.Min(float64(consecutiveFailures), 8)
	d := time.Duration(float64(baseInterval) * math.Pow(2, exp))
	if d > maxBackoff {
		d = maxBackoff
	}
	// ±10% jitter
	jitter := time.Duration(float64(d) * (0.1 * (2*rand.Float64() - 1)))
	return d + jitter
}

func main() {
	showVersion := flag.Bool("version", false, "Print version and exit")
	server := flag.String("server", os.Getenv("PLOW_SERVER"), "Plow server URL")
	run := flag.Bool("run", false, "Run the agent (used by service manager or for interactive/Docker mode)")
	svcAction := flag.String("service", "", "Service control: install, uninstall, start, stop, restart, status")
	copyCredsFrom := flag.String("copy-creds-from", "", "Copy credentials from this directory to the service data dir (used internally by the wizard)")
	flag.Parse()

	if *showVersion {
		fmt.Println("plow-agent", version)
		os.Exit(0)
	}

	// --copy-creds-from: internal flag used by the wizard's sudo step
	// to copy user credentials into the service data directory.
	if *copyCredsFrom != "" {
		copyCredentials(*copyCredsFrom)
		return
	}

	// --run: run the fetch loop (service manager invokes this, or Docker/interactive use)
	if *run {
		if *server == "" {
			fmt.Fprintln(os.Stderr, "Error: --server or PLOW_SERVER is required with --run")
			flag.Usage()
			os.Exit(1)
		}
		runAgent(*server)
		return
	}

	// --service <action>: power-user service control
	if *svcAction != "" {
		switch *svcAction {
		case "status":
			printServiceStatus(*server)
		case "logs":
			tailLogs()
		default:
			// For install, we need the server URL to bake into the service config
			if *svcAction == "install" && *server == "" {
				fmt.Fprintln(os.Stderr, "Error: --server or PLOW_SERVER is required for service install")
				flag.Usage()
				os.Exit(1)
			}
			controlService(*svcAction, *server)
		}
		return
	}

	// No args: friend-friendly interactive install wizard
	installWizard(*server)
}

// runAgent starts the fetch loop, either under the service manager or interactively.
// When running under the service manager, service.Interactive() returns false and
// the kardianos/service framework handles Start/Stop lifecycle.
// When running interactively (Docker, --run from terminal), it runs the same way
// but responds to Ctrl+C via the service framework's console handler.
func runAgent(serverURL string) {
	prg := &plowService{server: serverURL}
	svcCfg := serviceConfig(serverURL)

	s, err := service.New(prg, svcCfg)
	if err != nil {
		log.Fatalf("Failed to create service: %v", err)
	}

	logger, err := s.Logger(nil)
	if err != nil {
		log.Fatalf("Failed to create logger: %v", err)
	}
	prg.logger = logger

	if service.Interactive() {
		log.Printf("plow-agent %s — running interactively (Ctrl+C to stop)", version)
	} else {
		logger.Infof("plow-agent %s — running as system service", version)
	}

	if err := s.Run(); err != nil {
		logger.Errorf("Service exited with error: %v", err)
		os.Exit(1)
	}
}

// controlService sends a control action to the system service manager.
// If the action requires root and we're not root, re-execs via sudo.
func controlService(action, serverURL string) {
	switch action {
	case "install", "uninstall", "start", "stop", "restart":
		// These all need root on macOS/Linux
		if needsElevation() {
			fmt.Println("Service management requires elevated privileges, requesting via sudo...")
			args := []string{"--service", action}
			if serverURL != "" {
				args = append(args, "--server", serverURL)
			}
			os.Exit(reexecWithSudo(args))
		}

		prg := &plowService{}
		svcCfg := serviceConfig(serverURL)

		s, err := service.New(prg, svcCfg)
		if err != nil {
			log.Fatalf("Failed to create service: %v", err)
		}

		// On install, clear any stale service state first. launchd (macOS)
		// throttles services that crash-looped, so a reinstall without
		// bootout first will fail with "Input/output error" on start.
		if action == "install" {
			_ = service.Control(s, "stop")
			_ = service.Control(s, "uninstall")
		}

		err = service.Control(s, action)
		if err != nil {
			// launchd throttles services that previously crash-looped.
			// A plain "start" can fail with "Input/output error" even
			// though the plist is fine. Recover by doing a full
			// uninstall → install → start cycle.
			if (action == "start" || action == "restart") && strings.Contains(err.Error(), "Input/output error") {
				// Need a server URL to rebuild the plist
				if serverURL == "" {
					serverURL = readServerURLFromPlist()
				}
				if serverURL == "" {
					log.Fatalf("Failed to %s service: %v\nCannot recover: no server URL for reinstall. Use --server.", action, err)
				}
				fmt.Println("Service is throttled by launchd, reinstalling...")
				// Rebuild with the correct server URL
				svcCfg = serviceConfig(serverURL)
				s, _ = service.New(prg, svcCfg)
				_ = service.Control(s, "stop")
				_ = service.Control(s, "uninstall")
				if ierr := service.Control(s, "install"); ierr != nil {
					log.Fatalf("Failed to reinstall service: %v", ierr)
				}
				if serr := service.Control(s, "start"); serr != nil {
					// KeepAlive might start it anyway — check after a moment
					time.Sleep(2 * time.Second)
					if st, sterr := s.Status(); sterr == nil && st == service.StatusRunning {
						fmt.Println("Service is running.")
					} else {
						log.Fatalf("Failed to start service after reinstall: %v", serr)
					}
				} else {
					fmt.Println("Service started successfully.")
				}
			} else {
				log.Fatalf("Failed to %s service: %v", action, err)
			}
		} else {
			fmt.Printf("Service %sed successfully.\n", action)
		}
		if action == "install" {
			fmt.Println("Run 'plow-agent --service start' to start it, or it will start on next boot.")
		}
	default:
		fmt.Fprintf(os.Stderr, "Unknown service action: %s\n", action)
		fmt.Fprintf(os.Stderr, "Valid actions: install, uninstall, start, stop, restart, status, logs\n")
		os.Exit(1)
	}
}

// printServiceStatus shows the current service status with platform-specific info.
func printServiceStatus(serverURL string) {
	ph := getPlatformHelp()

	fmt.Printf("Platform:     %s (%s)\n", service.Platform(), ph.serviceType)
	fmt.Printf("Data dir:     %s\n", serviceDataDir)

	status := getServiceStatus()
	switch status {
	case service.StatusRunning:
		fmt.Printf("Status:       running\n")
	case service.StatusStopped:
		fmt.Printf("Status:       stopped\n")
	case service.StatusUnknown:
		fmt.Printf("Status:       not installed\n")
	default:
		fmt.Printf("Status:       unknown\n")
	}

	fmt.Println()
	printServiceCommands()
}

// printServiceCommands prints platform-aware management commands.
func printServiceCommands() {
	ph := getPlatformHelp()
	fmt.Println("Commands:")
	fmt.Println("  plow-agent --service status      Check if running")
	fmt.Println("  plow-agent --service logs         View live logs")
	fmt.Println("  plow-agent --service stop         Stop the service")
	fmt.Println("  plow-agent --service start        Start the service")
	fmt.Println("  plow-agent --service restart      Restart the service")
	fmt.Println("  plow-agent --service uninstall    Remove the service")
	fmt.Println()
	fmt.Printf("Logs (%s):\n", ph.serviceType)
	fmt.Printf("  %s\n", ph.logsCmd)
}

// installWizard is the friend-friendly path: prompt for config, install as
// a system service, and start it. This runs when the binary is double-clicked
// or invoked with no arguments.
func installWizard(serverURL string) {
	fmt.Println("=== Plow Agent Setup ===")
	fmt.Printf("Version: %s\n", version)
	fmt.Printf("Platform: %s\n", service.Platform())
	fmt.Println()

	// Check if already installed
	prg := &plowService{}
	status := getServiceStatus()
	if status != service.StatusUnknown {
		switch status {
		case service.StatusRunning:
			fmt.Println("The plow-agent service is already installed and running.")
			fmt.Println()
			printServiceCommands()
			return
		case service.StatusStopped:
			fmt.Println("The plow-agent service is installed but stopped.")
			fmt.Println()
			if confirm("Start it now?") {
				// Use restart (which does uninstall→install→start) to
				// clear any launchd throttle state. Always pass the
				// server URL so a reinstall can rebuild the plist.
				srvURL := serverURL
				if srvURL == "" {
					srvURL = readServerURLFromPlist()
				}
				if srvURL == "" {
					srvURL = "https://plow.jackharrhy.dev"
				}
				if needsElevation() {
					os.Exit(reexecWithSudo([]string{"--service", "restart", "--server", srvURL}))
				}
				controlService("restart", srvURL)
			}
			return
		}
	}

	// Not installed — run the wizard
	fmt.Println("This will install plow-agent as a system service so it runs")
	fmt.Println("automatically in the background, even after reboots.")
	fmt.Println()

	// Get server URL
	if serverURL == "" {
		serverURL = prompt("Server URL", "https://plow.jackharrhy.dev")
	}
	fmt.Printf("Server: %s\n", serverURL)

	// Ensure we have a name and keypair before installing
	// This triggers the interactive name prompt if needed
	fmt.Println()
	fmt.Println("Setting up credentials...")
	cfg := loadOrCreateConfig(serverURL)
	if !cfg.registered {
		register(cfg)
	}
	fmt.Printf("Agent ID: %s\n", cfg.agentID)
	fmt.Printf("Agent name: %s\n", cfg.name)
	fmt.Printf("Config dir: %s\n", cfg.configDir)
	fmt.Println()

	// Install and start the service.
	// If we need root, delegate via sudo. We need three sudo steps:
	// 1. Copy credentials to the service data directory
	// 2. Install the service
	// 3. Start the service
	if needsElevation() {
		fmt.Println()
		fmt.Println("Copying credentials to service directory (requires sudo)...")
		code := reexecWithSudo([]string{"--copy-creds-from", cfg.configDir})
		if code != 0 {
			fmt.Println("Failed to copy credentials.")
			os.Exit(code)
		}
		fmt.Println("Installing system service...")
		code = reexecWithSudo([]string{"--service", "install", "--server", serverURL})
		if code != 0 {
			fmt.Println()
			fmt.Println("You can also run interactively without installing a service:")
			fmt.Printf("  plow-agent --run --server %s\n", serverURL)
			os.Exit(code)
		}
		fmt.Println("Starting service...")
		code = reexecWithSudo([]string{"--service", "start", "--server", serverURL})
		if code != 0 {
			fmt.Println("Try: sudo plow-agent --service start")
			os.Exit(code)
		}
	} else {
		// Already running as root — copy credentials directly
		copyCredentials(cfg.configDir)

		svcCfg := serviceConfig(serverURL)
		s, err := service.New(prg, svcCfg)
		if err != nil {
			log.Fatalf("Failed to create service: %v", err)
		}
		_ = err // used above

		// Clear stale service state before installing (same as controlService)
		_ = service.Control(s, "stop")
		_ = service.Control(s, "uninstall")

		fmt.Println("Installing system service...")
		if ierr := s.Install(); ierr != nil {
			fmt.Printf("Failed to install service: %v\n", ierr)
			fmt.Println()
			fmt.Println("You can also run interactively instead:")
			fmt.Printf("  plow-agent --run --server %s\n", serverURL)
			os.Exit(1)
		}
		fmt.Println("Service installed!")

		fmt.Println("Starting service...")
		if serr := s.Start(); serr != nil {
			// launchd with KeepAlive may start the service on its own schedule;
			// wait briefly and check if it came up anyway.
			time.Sleep(2 * time.Second)
			if getServiceStatus() == service.StatusRunning {
				fmt.Println("Service is running.")
			} else {
				fmt.Printf("Failed to start: %v\n", serr)
				fmt.Println("Try: plow-agent --service start")
				os.Exit(1)
			}
		}
	}
	fmt.Println()
	fmt.Println("Done! The plow-agent is now running as a system service.")
	fmt.Println("It will start automatically on boot.")
	fmt.Println()
	fmt.Println("Your agent is waiting for approval. Let Jack know you've set")
	fmt.Println("it up so he can approve it — once approved, it will begin")
	fmt.Println("collecting plow data automatically.")
	fmt.Println()
	printServiceCommands()
}

// copyCredentials copies key.pem and name from srcDir to the service data
// directory. This runs as root via sudo during the wizard install step.
func copyCredentials(srcDir string) {
	destDir := serviceDataDir
	if err := os.MkdirAll(destDir, 0700); err != nil {
		log.Fatalf("Failed to create service data dir %s: %v", destDir, err)
	}

	for _, name := range []string{"key.pem", "name"} {
		src := filepath.Join(srcDir, name)
		data, err := os.ReadFile(src)
		if err != nil {
			log.Fatalf("Failed to read %s: %v", src, err)
		}
		dest := filepath.Join(destDir, name)
		if err := os.WriteFile(dest, data, 0600); err != nil {
			log.Fatalf("Failed to write %s: %v", dest, err)
		}
		fmt.Printf("Copied %s → %s\n", src, dest)
	}
}

// getServiceStatus returns the actual service status, working around
// kardianos/service limitations. On macOS, kardianos uses `launchctl list`
// which only searches the user domain — it can't see system daemons in
// /Library/LaunchDaemons/ without root. We use `launchctl print system/<name>`
// instead, which works without elevation.
func getServiceStatus() service.Status {
	if runtime.GOOS == "darwin" {
		out, err := exec.Command("launchctl", "print", "system/"+serviceName).CombinedOutput()
		if err != nil {
			// Not loaded at all
			if _, statErr := os.Stat("/Library/LaunchDaemons/" + serviceName + ".plist"); statErr == nil {
				return service.StatusStopped
			}
			return service.StatusUnknown
		}
		if strings.Contains(string(out), "state = running") {
			return service.StatusRunning
		}
		return service.StatusStopped
	}

	// For other platforms, kardianos Status() works fine
	prg := &plowService{}
	svcCfg := serviceConfig("")
	s, err := service.New(prg, svcCfg)
	if err != nil {
		return service.StatusUnknown
	}
	st, err := s.Status()
	if err != nil {
		return service.StatusUnknown
	}
	return st
}

// platformHelp returns platform-specific help strings.
type platformHelp struct {
	logsCmd     string // command to tail logs
	serviceType string // "launchd", "systemd", etc.
	plistPath   string // macOS only
}

func getPlatformHelp() platformHelp {
	switch runtime.GOOS {
	case "darwin":
		return platformHelp{
			logsCmd:     "tail -f /var/log/plow-agent.err.log",
			serviceType: "launchd",
			plistPath:   "/Library/LaunchDaemons/plow-agent.plist",
		}
	case "linux":
		return platformHelp{
			logsCmd:     "journalctl -u plow-agent -f",
			serviceType: "systemd",
		}
	case "windows":
		return platformHelp{
			logsCmd:     "Get-EventLog -LogName Application -Source plow-agent -Newest 50",
			serviceType: "Windows Service",
		}
	default:
		return platformHelp{
			logsCmd:     "cat /var/log/plow-agent.err.log",
			serviceType: "unknown",
		}
	}
}

// tailLogs execs into the platform-appropriate log viewer.
// On macOS/Linux this replaces the current process with tail/journalctl.
func tailLogs() {
	ph := getPlatformHelp()
	fmt.Printf("Showing logs (%s)...\n\n", ph.serviceType)

	switch runtime.GOOS {
	case "darwin":
		// Check if the log file exists first
		if _, err := os.Stat("/var/log/plow-agent.err.log"); err != nil {
			fmt.Println("No log file found at /var/log/plow-agent.err.log")
			fmt.Println("The service may not have started yet.")
			os.Exit(1)
		}
		cmd := exec.Command("tail", "-f", "/var/log/plow-agent.err.log")
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
		cmd.Stdin = os.Stdin
		if err := cmd.Run(); err != nil {
			if exitErr, ok := err.(*exec.ExitError); ok {
				os.Exit(exitErr.ExitCode())
			}
			os.Exit(1)
		}
	case "linux":
		cmd := exec.Command("journalctl", "-u", "plow-agent", "-f")
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
		cmd.Stdin = os.Stdin
		if err := cmd.Run(); err != nil {
			// journalctl may not exist — fall back to log file
			cmd2 := exec.Command("tail", "-f", "/var/log/plow-agent.err.log")
			cmd2.Stdout = os.Stdout
			cmd2.Stderr = os.Stderr
			cmd2.Stdin = os.Stdin
			cmd2.Run()
		}
	default:
		fmt.Printf("Run: %s\n", ph.logsCmd)
	}
}

// readServerURLFromPlist reads the server URL from an existing launchd plist
// by looking at the ProgramArguments for --server <value>.
// Returns empty string if not found.
func readServerURLFromPlist() string {
	plistPath := "/Library/LaunchDaemons/plow-agent.plist"
	data, err := os.ReadFile(plistPath)
	if err != nil {
		return ""
	}
	content := string(data)

	// The plist has <string>--server</string><string>URL</string> in the
	// ProgramArguments array. Find "--server" and grab the next <string>.
	const marker = "<string>--server</string>"
	idx := strings.Index(content, marker)
	if idx < 0 {
		return ""
	}
	rest := content[idx+len(marker):]
	// Skip whitespace to the next <string>
	start := strings.Index(rest, "<string>")
	if start < 0 {
		return ""
	}
	rest = rest[start+len("<string>"):]
	end := strings.Index(rest, "</string>")
	if end < 0 {
		return ""
	}
	return strings.TrimSpace(rest[:end])
}

// needsElevation returns true if the current process is not running as root
// on a platform where service install/uninstall requires it (macOS, Linux).
func needsElevation() bool {
	if runtime.GOOS == "windows" {
		return false // Windows uses UAC, not sudo
	}
	return os.Geteuid() != 0
}

// reexecWithSudo re-executes the current binary via sudo with the given
// arguments. It connects stdin/stdout/stderr so the user sees the sudo
// password prompt and all output. Returns the exit code.
func reexecWithSudo(args []string) int {
	exe, err := os.Executable()
	if err != nil {
		fmt.Fprintf(os.Stderr, "Cannot determine executable path: %v\n", err)
		return 1
	}
	sudoArgs := append([]string{exe}, args...)
	cmd := exec.Command("sudo", sudoArgs...)
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			return exitErr.ExitCode()
		}
		return 1
	}
	return 0
}

// prompt asks the user for input with a default value.
func prompt(label, defaultValue string) string {
	if defaultValue != "" {
		fmt.Printf("%s [%s]: ", label, defaultValue)
	} else {
		fmt.Printf("%s: ", label)
	}
	scanner := bufio.NewScanner(os.Stdin)
	if scanner.Scan() {
		val := strings.TrimSpace(scanner.Text())
		if val != "" {
			return val
		}
	}
	return defaultValue
}

// confirm asks a yes/no question, defaulting to yes.
func confirm(question string) bool {
	fmt.Printf("%s [Y/n]: ", question)
	scanner := bufio.NewScanner(os.Stdin)
	if scanner.Scan() {
		val := strings.TrimSpace(strings.ToLower(scanner.Text()))
		return val == "" || val == "y" || val == "yes"
	}
	return true
}
