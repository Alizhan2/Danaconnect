import type { NextConfig } from 'next';
const apiBase = (process.env.API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const nextConfig: NextConfig = {
  output: 'standalone',
  turbopack: { root: process.cwd() },
  poweredByHeader: false,
  async headers() {
    return [{ source: '/:path*', headers: [
      { key: 'X-Content-Type-Options', value: 'nosniff' },
      { key: 'X-Frame-Options', value: 'DENY' },
      { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
    ] }];
  },
  async rewrites() { return [{ source: '/api/v1/:path*', destination: `${apiBase}/api/v1/:path*` }]; },
};
export default nextConfig;
