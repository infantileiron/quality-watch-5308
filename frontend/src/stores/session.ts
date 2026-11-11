import type {User} from '../types/entities';
export function savedUser():User|null {try{return JSON.parse(sessionStorage.getItem('quality-user')||'null')}catch{return null}}
export function saveSession(token:string,user:User){sessionStorage.setItem('quality-token',token);sessionStorage.setItem('quality-user',JSON.stringify(user))}
export function clearSession(){sessionStorage.removeItem('quality-token');sessionStorage.removeItem('quality-user')}
