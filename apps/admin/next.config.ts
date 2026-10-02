import type { NextConfig } from 'next';
const apiBase = (process.env.API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const basePath = process.env.ADMIN_BASE_PATH || '';
const config: NextConfig = {
  basePath, env: {NEXT_PUBLIC_ADMIN_BASE_PATH: basePath},
  output: 'standalone', poweredByHeader: false, turbopack: {root: process.cwd()},
  async headers() {
    return [{source:'/:path*',headers:[
      {key:'X-Content-Type-Options',value:'nosniff'},
      {key:'X-Frame-Options',value:'DENY'},
      {key:'Referrer-Policy',value:'strict-origin-when-cross-origin'},
    ]},{source:'/accept-invite',headers:[
      {key:'Referrer-Policy',value:'no-referrer'},
      {key:'Cache-Control',value:'no-store'},
    ]}];
  },
  async rewrites() { return [{source:'/api/v1/:path*',destination:`${apiBase}/api/v1/:path*`,basePath:false}]; },
};
export default config;
