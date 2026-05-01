/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // Backend URL is read from env at runtime by the page component.
  env: {
    BACKEND_URL: process.env.BACKEND_URL || "http://localhost:8000",
  },
};

module.exports = nextConfig;
