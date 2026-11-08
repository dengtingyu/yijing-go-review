import {GoTerrain} from './terrain.js';
const connection=document.getElementById('connection');
try{
  const view=new GoTerrain(document.getElementById('terrain'));let revision=-1;
  async function poll(){
    try{
      const response=await fetch('/api/terrain',{cache:'no-store'});
      if(!response.ok)throw Error('服务未就绪');
      const state=await response.json();
      connection.textContent=state.connected?'已连接 Lizzie / KataGo · 换手、退棋和试下自动跟随':'引擎已退出';
      if(state.revision!==revision){revision=state.revision;view.update(state)}
    }catch(error){connection.textContent='联动尚未连接；请在 Lizzie 中启用「KataGo · 3D 形势」引擎。'}
    setTimeout(poll,650);
  }
  poll();
}catch(error){connection.textContent='无法启动 3D 视图：'+error.message}
