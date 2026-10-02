export class ApiError extends Error { constructor(public status:number, message:string,public requestId?:string) {super(message);this.name='ApiError';} }
function responseRequestId(response:Response){const value=response.headers.get('X-Request-ID');return value&&/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value)?value:undefined;}
export async function api<T>(path:string,options:RequestInit={}):Promise<T>{
  if(!path.startsWith('/')||path.startsWith('//')||path.startsWith('/api/v1'))throw new Error('Invalid API route');
  const headers=new Headers(options.headers);if(options.body)headers.set('Content-Type','application/json');
  headers.set('Accept-Language',typeof document==='undefined'?'ru':document.documentElement.lang);
  let response:Response;try{response=await fetch(`/api/v1${path}`,{...options,headers,credentials:'include',cache:'no-store',signal:options.signal??AbortSignal.timeout(25000)});}catch{throw new ApiError(0,'Network unavailable');}
  const data=response.status===204?null:await response.json().catch(()=>null);
  if(!response.ok)throw new ApiError(response.status,typeof data?.detail==='string'?data.detail:`HTTP ${response.status}`,responseRequestId(response));return data;
}
export const mutate=<T,>(path:string,body?:unknown,method='POST')=>api<T>(path,{method,...(body===undefined?{}:{body:JSON.stringify(body)})});
export function safeUrl(value?:string|null){try{const url=new URL(value||'');return ['http:','https:'].includes(url.protocol)&&!url.username&&!url.password?url.href:undefined;}catch{return undefined;}}
