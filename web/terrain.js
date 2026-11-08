import * as THREE from './vendor/three.module.js';
import {OrbitControls} from './vendor/OrbitControls.js';

const COLS='ABCDEFGHJKLMNOPQRST';
const smoothstep=t=>t*t*t*(t*(t*6-15)+10);

// Shared by the review page and the GTP companion. Coordinates run top-left first.
export class GoTerrain {
  constructor(host,{onPlay}={}) {
    this.host=host; this.onPlay=onPlay; this.visible=true;
    host.innerHTML='<div class="terrain-stage"><canvas aria-label="三维 AI 归属地形，拖动旋转，滚轮缩放"></canvas></div><div class="terrain-toolbar"><span>拖动旋转 · 滚轮缩放 · 右键平移</span><button type="button" data-reset>恢复 45°</button><label><input type="checkbox" data-surface checked> 显示地形</label></div><p class="terrain-caption" aria-live="polite"></p>';
    this.stage=host.querySelector('.terrain-stage');
    this.caption=host.querySelector('.terrain-caption');
    this.canvas=host.querySelector('canvas');
    this.renderer=new THREE.WebGLRenderer({canvas:this.canvas,alpha:true,antialias:true});
    this.renderer.setPixelRatio(Math.min(devicePixelRatio||1,2));
    this.renderer.outputColorSpace=THREE.SRGBColorSpace;
    this.scene=new THREE.Scene();
    this.camera=new THREE.PerspectiveCamera(37,1,.1,180);
    this.controls=new OrbitControls(this.camera,this.canvas);
    this.controls.target.set(0,1.5,0);this.controls.minDistance=25;this.controls.maxDistance=85;
    this.controls.minPolarAngle=Math.PI/36;this.controls.maxPolarAngle=Math.PI*80/180;
    this.controls.rotateSpeed=.7;this.controls.zoomSpeed=.8;
    this.controls.addEventListener('change',()=>this.draw());
    this.scene.add(new THREE.HemisphereLight(0xffffff,0x657471,1.3));
    const light=new THREE.DirectionalLight(0xffffff,1.7);light.position.set(-10,24,12);this.scene.add(light);
    const fill=new THREE.DirectionalLight(0xffffff,1);fill.position.set(12,10,-14);this.scene.add(fill);
    this.boardGroup=new THREE.Group();this.stoneGroup=new THREE.Group();this.surfaceGroup=new THREE.Group();
    this.scene.add(this.boardGroup,this.stoneGroup,this.surfaceGroup);
    host.querySelector('[data-reset]').onclick=()=>this.reset();
    host.querySelector('[data-surface]').onchange=e=>{this.surfaceGroup.visible=e.target.checked;this.draw()};
    this.observer=new ResizeObserver(()=>this.resize());this.observer.observe(this.stage);
    this.raycaster=new THREE.Raycaster();this.pointer=new THREE.Vector2();
    let down;
    this.canvas.addEventListener('pointerdown',e=>{down=[e.clientX,e.clientY]});
    this.canvas.addEventListener('pointerup',e=>{
      if(!down||Math.hypot(e.clientX-down[0],e.clientY-down[1])>5||e.button!==0)return;
      if(!this.onPlay||!this.data)return;
      const rect=this.canvas.getBoundingClientRect();
      this.pointer.set((e.clientX-rect.left)/rect.width*2-1,-(e.clientY-rect.top)/rect.height*2+1);
      this.raycaster.setFromCamera(this.pointer,this.camera);
      const hit=this.surfaceGroup.visible&&this.terrain?this.raycaster.intersectObject(this.terrain)[0]:null;
      const pos=hit?.point||this.raycaster.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0,1,0),0),new THREE.Vector3());
      if(!pos||Math.abs(pos.x)>9.45||Math.abs(pos.z)>9.45)return;
      const n=this.data.size,x=Math.round((pos.x+9)/18*(n-1)),y=Math.round((pos.z+9)/18*(n-1));
      if(x>=0&&y>=0&&x<n&&y<n)this.onPlay(COLS[x]+(n-y));
    });
    this.reset();this.resize();
  }
  reset(){this.controls.target.set(0,1.5,0);this.camera.position.setFromSpherical(new THREE.Spherical(46,Math.PI/4,Math.PI/4)).add(this.controls.target);this.controls.update();this.draw()}
  resize(){const w=this.stage.clientWidth,h=this.stage.clientHeight;if(!w||!h)return;this.renderer.setSize(w,h,false);this.camera.aspect=w/h;this.camera.updateProjectionMatrix();this.draw()}
  draw(){if(this.visible)this.renderer.render(this.scene,this.camera)}
  setVisible(value){this.visible=value;if(value)this.resize()}
  clear(group){for(const mesh of [...group.children]){group.remove(mesh);mesh.geometry?.dispose();for(const mat of Array.isArray(mesh.material)?mesh.material:[mesh.material]){mat?.map?.dispose();mat?.dispose()}}}
  label(text,x,z){const c=document.createElement('canvas');c.width=128;c.height=64;const ctx=c.getContext('2d');ctx.font='500 34px system-ui';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillStyle='#61563e';ctx.fillText(text,64,32);const mesh=new THREE.Sprite(new THREE.SpriteMaterial({map:new THREE.CanvasTexture(c),depthTest:false}));mesh.position.set(x,.12,z);mesh.scale.set(.85,.425,1);this.boardGroup.add(mesh)}
  board(n){
    this.clear(this.boardGroup);
    const board=new THREE.Mesh(new THREE.BoxGeometry(20.4,.45,20.4),new THREE.MeshStandardMaterial({color:0xe6c27f,roughness:.87}));board.position.y=-.25;this.boardGroup.add(board);
    const vertices=[],step=18/(n-1);
    for(let i=0;i<n;i++){const c=i*step-9;vertices.push(-9,.015,c,9,.015,c,c,.015,-9,c,.015,9);this.label(COLS[i],c,9.7);this.label(String(n-i),9.7,c)}
    const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));this.boardGroup.add(new THREE.LineSegments(geo,new THREE.LineBasicMaterial({color:0x795b35,transparent:true,opacity:.6})));
    const stars=n===19?[3,9,15]:n===13?[3,6,9]:[2,4,6];
    for(const x of stars)for(const y of stars){if(n===9&&x!==y&&x+y!==8)continue;const star=new THREE.Mesh(new THREE.SphereGeometry(.065,12,8),new THREE.MeshBasicMaterial({color:0x70512e}));star.scale.y=.16;star.position.set(x*step-9,.03,y*step-9);this.boardGroup.add(star)}
  }
  update(data){
    if(!data||![9,13,19].includes(data.size))return;
    const n=data.size,previous=this.data;this.data=data;
    if(previous?.size!==n)this.board(n);
    if(previous?.stones!==data.stones||previous?.size!==n){
      this.clear(this.stoneGroup);const step=18/(n-1),radius=step*.43;
      data.stones.forEach((v,i)=>{if(!v)return;const mesh=new THREE.Mesh(new THREE.SphereGeometry(radius,24,16),new THREE.MeshStandardMaterial({color:v===1?0x171d1c:0xf0eee6,roughness:v===1?.3:.4,metalness:v===1?.08:0}));mesh.scale.y=.42;mesh.position.set(i%n*step-9,radius*.42,Math.floor(i/n)*step-9);this.stoneGroup.add(mesh)});
    }
    if(previous?.ownership!==data.ownership||previous?.size!==n){
      this.clear(this.surfaceGroup);this.terrain=null;
      if(Array.isArray(data.ownership)&&data.ownership.length===n*n&&data.ownership.every(Number.isFinite))this.surface(data.ownership,n);
    }
    this.caption.textContent=data.message||`${data.turn??0} 手 · ${this.terrain?`${(data.visits||0).toLocaleString()} 次搜索 · 黑色偏黑方，白色偏白方；高度表示归属倾向`:'等待当前局面分析，暂不显示地形'}`;
    this.draw();
  }
  surface(values,n){
    const smoothed=values.map((_,i)=>{const x=i%n,y=Math.floor(i/n);let sum=0,weights=0;for(let dy=-2;dy<=2;dy++)for(let dx=-2;dx<=2;dx++){const xx=x+dx,yy=y+dy;if(xx<0||xx>=n||yy<0||yy>=n)continue;const w=Math.exp(-(dx*dx+dy*dy)/(2*.8*.8));sum+=values[yy*n+xx]*w;weights+=w}return sum/weights});
    const ownership=(x,z)=>{const fx=THREE.MathUtils.clamp((x+9)/18*(n-1),0,n-1),fy=THREE.MathUtils.clamp((z+9)/18*(n-1),0,n-1),ix=Math.min(n-2,Math.floor(fx)),iy=Math.min(n-2,Math.floor(fy)),a=fx-ix,b=fy-iy;return smoothed[iy*n+ix]*(1-a)*(1-b)+smoothed[iy*n+ix+1]*a*(1-b)+smoothed[(iy+1)*n+ix]*(1-a)*b+smoothed[(iy+1)*n+ix+1]*a*b};
    const edge=c=>1-smoothstep(THREE.MathUtils.clamp((Math.abs(c)-7.2)/2.25,0,1));
    const elevation=(x,z)=>.025+(.095+4.2*Math.pow(Math.abs(ownership(x,z)),1.15))*edge(x)*edge(z);
    const resolution=126,vertices=[],colors=[],indices=[],black=new THREE.Color(0x1c2523),white=new THREE.Color(0xf6f4ed),neutral=new THREE.Color(0xaaa99e);
    for(let row=0;row<=resolution;row++)for(let col=0;col<=resolution;col++){const x=(col/resolution-.5)*18.9,z=(row/resolution-.5)*18.9,v=ownership(x,z);vertices.push(x,elevation(x,z),z);const c=neutral.clone().lerp(v>=0?black:white,Math.pow(Math.abs(v),.65));colors.push(c.r,c.g,c.b)}
    for(let r=0;r<resolution;r++)for(let c=0;c<resolution;c++){const a=r*(resolution+1)+c,b=a+1,d=a+resolution+1,e=d+1;indices.push(a,d,b,b,d,e)}
    const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));geo.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));geo.setIndex(indices);geo.computeVertexNormals();
    this.terrain=new THREE.Mesh(geo,new THREE.MeshStandardMaterial({vertexColors:true,roughness:.72,metalness:.04,transparent:true,opacity:.64,side:THREE.DoubleSide,depthWrite:false}));this.terrain.renderOrder=2;this.surfaceGroup.add(this.terrain);
    const lines=[];
    for(let axis=0;axis<2;axis++)for(let a=0;a<n;a++)for(let b=0;b<72;b++){const u=a/(n-1)*18-9,v=b/4-9,w=(b+1)/4-9,x1=axis?v:u,z1=axis?u:v,x2=axis?w:u,z2=axis?u:w;lines.push(x1,elevation(x1,z1)+.025,z1,x2,elevation(x2,z2)+.025,z2)}
    const lineGeo=new THREE.BufferGeometry();lineGeo.setAttribute('position',new THREE.Float32BufferAttribute(lines,3));const contours=new THREE.LineSegments(lineGeo,new THREE.LineBasicMaterial({color:0x20372e,transparent:true,opacity:.12,depthWrite:false}));contours.renderOrder=3;this.surfaceGroup.add(contours);
  }
}
