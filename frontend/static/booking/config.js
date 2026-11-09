// Frontend configuration.
//
// When this page is served by the API's own Django server, the inline
// script in the template fills in the key automatically and apiBase stays
// empty (same-origin). To host this page somewhere else (GitHub Pages,
// S3, any static host), copy frontend/ and set BOTH fields here:
//
//   apiBase: origin of the deployed Clinic Booking API, no trailing slash
//   apiKey:  the CLINIC_API_KEY configured on that server
window.CLINIC_CONFIG = {
  apiBase: "",
  apiKey: "",
};
