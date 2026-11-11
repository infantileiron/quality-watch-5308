import {request} from './client';import type {Baseline} from '../types/entities';
export const list=()=>request<Baseline[]>('/baselines');export const create=(data:unknown)=>request<Baseline>('/baselines','POST',data);
