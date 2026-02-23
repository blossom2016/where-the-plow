# CBS Geotab Citizen Insights

**Status:** Not yet reverse-engineered -- proprietary SPA
**GitHub issue:** #16
**Tracker URL:** https://citizeninsights.geotab.com/#/equipment-tracker-cbs
**API type:** Unknown (proprietary Geotab platform)
**Platform:** Geotab Citizen Insights

## What We Know

CBS (Conception Bay South) uses Geotab's "Citizen Insights" platform, a
proprietary SPA (Single Page Application) for municipal equipment tracking.

### Web Application Structure

- **Frontend:** Minified JavaScript SPA (`/dist/main.js`)
- **Frameworks found in bundle:** Mithril.js, RxJS, Redux, Mapbox GL JS,
  DayJS, Lodash, DOMPurify, Turf.js
- **Map:** Mapbox GL JS (v1.12.0)
- **Analytics:** Google Tag Manager

### URLs Found in Bundle

| URL | Purpose |
|-----|---------|
| `https://analyticslab.geotab.com/` | Production API base (likely) |
| `https://analyticslab-staging.geotab.com/` | Staging API |
| `https://analyticslabtest.geotab.com/` | Test API |
| `https://citizeninsights.geotab.com` | Frontend origin |

### Storage

- Assets stored in Google Cloud Storage bucket:
  `geotab-citizen-insights-{environment}/`
- Environment is determined at runtime via `isProduction()` check

### Security Headers

The CSP (Content-Security-Policy) header restricts connections to:
- `self`
- `storage.googleapis.com`
- `*.google-analytics.com`
- `*.googletagmanager.com`
- `api.mapbox.com`
- `events.mapbox.com`

Notably, `analyticslab.geotab.com` is NOT in the connect-src CSP, which
suggests the API calls may go through the citizeninsights.geotab.com
origin (proxied) or the CSP may be incomplete.

## What We Don't Know

1. **API endpoint structure** -- the minified bundle obscures the API paths.
   Only `/api/.` was found via regex, suggesting dynamic URL construction.
2. **Authentication** -- unclear if the API requires tokens, cookies, or
   is open
3. **Data shape** -- no sample response available
4. **Rate limits** -- unknown
5. **Whether "cbs" is a route parameter or a configuration** -- the hash
   URL `#/equipment-tracker-cbs` suggests it's a client-side route, and
   "cbs" may be passed as a parameter to the API

## Reverse Engineering Approaches (for future agents)

### Approach 1: Browser DevTools (Recommended)

The most reliable approach is to open the tracker in a browser with DevTools
Network tab and observe the actual API requests:

1. Navigate to `https://citizeninsights.geotab.com/#/equipment-tracker-cbs`
2. Open DevTools > Network tab
3. Filter by XHR/Fetch requests
4. Observe the requests made on load and during polling
5. Document: URL, method, headers, request body, response shape

### Approach 2: Deeper Bundle Analysis

The minified bundle at `/dist/main.js` is ~1.5MB. More thorough analysis
could reveal:

1. Search for `equipment-tracker` in the bundle to find the component
2. Search for `axios` or `fetch` patterns near that code
3. Look for URL template strings with "cbs" as a parameter
4. The bundle uses axios for HTTP -- search for axios interceptors for
   auth header patterns

### Approach 3: Try Known Patterns

Based on the Geotab Analytics Lab platform, try:

```
GET https://analyticslab.geotab.com/api/equipment-tracker/cbs
GET https://citizeninsights.geotab.com/api/equipment-tracker/cbs
GET https://analyticslab.geotab.com/api/v1/equipment/cbs
```

### Approach 4: Geotab SDK / Public API

Geotab has a public SDK (https://geotab.github.io/sdk/) with a MyGeotab
API. CBS may be using a standard Geotab fleet tracking setup. The Citizen
Insights platform might be a thin layer over the standard Geotab API.

## Implementation Priority

**Lowest priority** for multi-source implementation because:
1. Proprietary platform with no obvious public API
2. Requires manual browser-based reverse engineering
3. Other sources (Mt Pearl, Provincial) have known working APIs
4. CBS is a smaller municipality -- lower impact

## Map Center (estimated)

- Center: approximately (-52.95, 47.50)
- Zoom: 12
- Coverage: Town of Conception Bay South

## Notes for Future Research

- The Geotab platform appears to be used by multiple municipalities
  across Canada. If someone cracks the API for one Citizen Insights
  deployment, it likely works for all of them.
- The `equipment-tracker-cbs` route slug suggests there may be other
  equipment tracker deployments (search for other municipalities using
  Citizen Insights).
- Paradise's tracker at hitechmaps.com also appears to use Geotab on the
  backend (the frontend references Geotab-style fields), which suggests
  HitechMaps may be a Geotab reseller/integrator.
