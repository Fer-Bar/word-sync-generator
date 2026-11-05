import {createLyricsRenderer} from '/braccato/index.js';
import {forEveryLiveView} from '/braccato/engine.js';

// CSS cubic-bezier timing sampled against media time, never capture wall time.
function bezier(t, x1=.86, y1=0, x2=.2, y2=1) {
  t = Math.max(0, Math.min(1, t));
  const value = (u,a,b) => 3*(1-u)*(1-u)*u*a + 3*(1-u)*u*u*b + u*u*u;
  let lo=0, hi=1;
  for(let i=0;i<20;i++){const u=(lo+hi)/2;if(value(u,x1,x2)<t)lo=u;else hi=u;}
  return value((lo+hi)/2,y1,y2);
}
let renderer, scene, groups, records;
window.setup = async data => {
  scene=data;
  const ink = /^#[0-9a-f]{6}$/i.test(data.ink_color) ? data.ink_color : "#FFFFFF";
  const inactive = data.mode==='karaoke' && /^#[0-9a-f]{6}$/i.test(data.inactive_color)
    ? data.inactive_color : `color-mix(in srgb, ${ink} 30%, transparent)`;
  await document.fonts.load(`600 ${data.font_size}px Switzer`);
  renderer=createLyricsRenderer({document,window,mount:document.querySelector('#mount'),host:{
    isViewVisible:()=>true,isLoaderActive:()=>false,syncAdState:()=>false,
    getScrollElement:()=>document.querySelector('#mount'),log:()=>{}
  }});
  renderer.setTheme(`/* blyrics-letter-wave = false; */
    :root {--blyrics-font-family:Switzer;--blyrics-font-weight:600;
    --blyrics-font-size:${data.font_size}px;--blyrics-line-height:1.35;
    --blyrics-animate-scroll:0;--blyrics-animate-line-scale:0;
    --blyrics-richsync-timing-offset:0s;--blyrics-timing-offset:0s;
    --blyrics-scroll-timing-offset:0s;--blyrics-glow-color:color-mix(in srgb, ${ink} 50%, transparent);
    --blyrics-lyric-active-color:${ink};
    --blyrics-lyric-inactive-color:${inactive};}`);
  renderer.setLyrics(data.lyrics);
  records=renderer.lines;
  forEveryLiveView(engine=>{engine.lineCullObserver?.disconnect();engine.culledLineElements.clear();});
  const marginV = data.margin_v ?? Math.round(data.height * .22);
  document.querySelector('#mount').style.setProperty('--margin-v', `${marginV}px`);
  for(const record of records){
    record.lyricElement.style.left=`${data.margin}px`;
    record.lyricElement.style.width=`${data.width-2*data.margin}px`;
  }
  groups=data.groups.map(group=>{
    let cursor=0;
    const lines=group.indices.map(index=>{
      const record=records[index];
      const height=record.lyricElement.getBoundingClientRect().height;
      const result={index,y:cursor,height};cursor+=height+data.font_size*.4;
      return result;
    });
    return {...group,lines,height:cursor-data.font_size*.4};
  });
  // Fit unusually long pages without changing only one word's layout.
  for(const group of groups)group.scale=Math.min(1,(data.height*.65)/Math.max(1,group.height));
  let offset=0;
  for(const group of groups){group.offset=offset;offset+=group.height*group.scale+data.font_size*1.1;}
  renderer.relayout();
  for(const group of groups)for(const line of group.lines){
    const element=records[line.index].lyricElement;
    element.style.transform=`scale(${group.scale})`;
    if(scene.mode==='lyrics')element.style.top=`${(scene.height-group.height*group.scale)/2+line.y*group.scale}px`;
  }
  await document.fonts.ready;
  window.ready=true;
};
window.renderFrame = time => {
  if(!Number.isFinite(time)||time<0)throw new Error('Invalid frame time');
  let selected=-1;
  for(let i=0;i<groups.length;i++)if(time>=groups[i].start-.35)selected=i;
  if(selected<0)selected=0;
  const current=groups[selected];
  if(!current)return;
  const visible=time>=groups[0].start-.35 && time<=groups.at(-1).end+.85;
  const changing=selected>0 ? bezier((time-(current.start-.35))/.65) : 1;
  const scrollOffset=selected>0 ? groups[selected-1].offset*(1-changing)+current.offset*changing : current.offset;
  const activeLine=current.lines.findLast(line=>time>=records[line.index].time)?.index ?? current.lines[0].index;
  for(let i=0;i<groups.length;i++){
    const group=groups[i];
    const allowed=visible && (scene.mode==='karaoke' || i===selected && time<=group.end+.35);
    for(const line of group.lines){
      const element=records[line.index].lyricElement;
      const record=records[line.index];
      let y=scene.mode==='karaoke' ? scene.height*.45+group.offset-scrollOffset+line.y*group.scale
        : (scene.height-group.height*group.scale)/2+line.y*group.scale;
      if(scene.mode==='karaoke')element.style.top=`${y}px`;
      const inWindow=scene.mode!=='karaoke' || Math.abs(line.index-activeLine)<=1;
      const onScreen=allowed && inWindow && y>-group.height && y<scene.height;
      element.style.visibility=onScreen ? 'visible':'hidden';
      // Keep effects tied to media time, including when seeking across hidden lines.
      record.isAnimating=false;
      if(!onScreen)continue;
      if(scene.mode==='karaoke' && scene.inactive_color){
        const upcoming=line.index!==activeLine && time<record.time;
        for(const state of ['active','inactive']){
          const property=`--blyrics-lyric-${state}-color`;
          if(upcoming)element.style.setProperty(property,'#A8A8A8');
          // Braccato eventually removes its highlight layer; keep the completed base filled.
          else if(state==='inactive' && time>=record.time+record.duration)
            element.style.setProperty(property,'var(--blyrics-lyric-active-color)');
          else element.style.removeProperty(property);
        }
      }
      const rawPast=Math.max(0,Math.min(1,(time-record.time-record.duration-.35)/.5));
      const past=rawPast>0?bezier(rawPast,.4,0,.2,1):0;
      const future=time<record.time;
      element.dataset.state=rawPast>=1?'past':future?'future':'active';
      element.style.opacity=String(future ? .66 : 1-.67*past);
      element.style.filter=`blur(${2.5*scene.font_size/48*past}px)`;
    }
  }
  renderer.tick(time,{isPlaying:false,smoothScroll:false});
  document.querySelector('#mount').scrollTop=0;
  for(const animation of document.getAnimations())animation.pause();
};
window.lyricsDiagnostics = () => records.map(record=>({
  time:record.time,box:record.lyricElement.getBoundingClientRect().toJSON(),
  words:record.parts.map(part=>({text:part.lyricElement.textContent,
    box:part.lyricElement.getBoundingClientRect().toJSON(),
    transform:getComputedStyle(part.lyricElement).transform,
    glow:getComputedStyle(part.highlightElement).filter,
    gradient:getComputedStyle(part.highlightElement).backgroundImage,
    animations:part.animations.map(a=>({time:a.currentTime,state:a.playState}))}))
}));
window.moduleReady=true;
