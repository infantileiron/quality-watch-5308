import type {Result} from '../types/entities';
export function chartScale(r:Result){const values=r.series.flatMap(p=>[p.value,p.lcl,p.ucl]);values.push(r.study.lsl,r.study.usl);const low=Math.min(...values)-.006,high=Math.max(...values)+.006;return{x:(i:number)=>70+i/Math.max(1,r.series.length-1)*1010,y:(v:number)=>330-(v-low)/(high-low)*275,low,high}}
