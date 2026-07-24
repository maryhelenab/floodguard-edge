/*
Dashboard deployment configuration.

This file contains only public browser settings.
AWS credentials must never be stored in the dashboard.
*/

window.FLOODGUARD_CONFIG = {
  // Public API Gateway base URL, without a trailing slash.
  API_BASE_URL: "https://igsjnvt205.execute-api.us-east-1.amazonaws.com",

  // Refresh the dashboard every 10 seconds.
  REFRESH_INTERVAL_MS: 10000,

  // Stop waiting if the API does not respond within 8 seconds.
  REQUEST_TIMEOUT_MS: 8000
};
