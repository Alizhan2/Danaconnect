/** Invitation secrets stay in component memory. Query parameters never prove access. */
export function invitationToken(fragment:string):string|null{
  const params=new URLSearchParams(fragment.startsWith('#')?fragment.slice(1):fragment);
  const tokens=params.getAll('token');
  if(tokens.length!==1)return null;
  const value=tokens[0];
  return value.length>=32&&value.length<=128&&/^[A-Za-z0-9_-]+$/.test(value)?value:null;
}

export function consumeInvitationFragment(location:{hash:string;pathname:string;search:string},history:{state:unknown;replaceState:(state:unknown,unused:string,url:string)=>void}):string|null{
  const token=invitationToken(location.hash);
  // The invitation route has no query parameters. Strip accidental query secrets too.
  if(location.hash||location.search)history.replaceState(history.state,'',location.pathname);
  return token;
}

export function localQrImage(value:string):string|undefined{
  return value.length<=200000&&/^data:image\/svg\+xml;base64,[A-Za-z0-9+/]+={0,2}$/.test(value)?value:undefined;
}

export function secondsRemaining(deadline:number,now=Date.now()):number{
  return Math.max(0,Math.ceil((deadline-now)/1000));
}

export function canRevokeInvitation(status:string):boolean{return status==='pending';}
