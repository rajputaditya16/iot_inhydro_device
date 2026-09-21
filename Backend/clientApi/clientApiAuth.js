/**
 * Client API Authentication Middleware
 * Validates API key from request headers, query parameters, or Bearer tokens.
 */
const validateClientApiKey = (req, res, next) => {
  const configuredKey = process.env.CLIENT_API_KEY || 'inhydro_ai_dataset_key_2026';

  // Extract key from header, query param, or Authorization header
  let providedKey =
    req.headers['x-api-key'] ||
    req.headers['x-client-key'] ||
    req.query.apiKey ||
    req.query.api_key ||
    req.query.key;

  if (!providedKey && req.headers.authorization) {
    const authHeader = req.headers.authorization;
    if (authHeader.startsWith('ApiKey ') || authHeader.startsWith('Bearer ')) {
      providedKey = authHeader.split(' ')[1];
    } else {
      providedKey = authHeader;
    }
  }

  // If no configured key required or keys match
  if (configuredKey && providedKey !== configuredKey) {
    return res.status(401).json({
      success: false,
      message: 'Unauthorized: Invalid or missing API Key for AI Client Data API.',
      hint: 'Please provide a valid API key in header "x-api-key: <KEY>" or query param "?apiKey=<KEY>"'
    });
  }

  next();
};

module.exports = { validateClientApiKey };
