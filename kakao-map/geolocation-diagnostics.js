(function (root) {
  // A browser estimate may be coarse. Keep the best fresh fix and expose its quality.
  function requestLocation({geolocation, onProgress, onResult, timeoutMs=30000, targetAccuracy=200}) {
    let active=true, watchId=null, best=null, lastError=null;
    const finish=result=>{
      if(!active)return;
      active=false;clearTimeout(timer);
      if(watchId!==null)geolocation.clearWatch(watchId);
      onResult(result);
    };
    const timer=setTimeout(()=>finish(best?{kind:'approximate',position:best}:{kind:'unavailable',...(lastError||{code:3,message:'30초 동안 기기에서 위치를 받지 못했습니다.'})}),timeoutMs);
    try {
      watchId=geolocation.watchPosition(position=>{
        if(!active)return;
        const {latitude,longitude,accuracy}=position.coords;
        if(!Number.isFinite(latitude)||!Number.isFinite(longitude)||Math.abs(latitude)>90||Math.abs(longitude)>180||!Number.isFinite(accuracy)||accuracy<0)return;
        if(Number.isFinite(position.timestamp)&&Date.now()-position.timestamp>60000)return;
        if(best&&best.accuracy<=accuracy)return;
        best={latitude,longitude,accuracy};
        if(accuracy<=targetAccuracy)finish({kind:'accurate',position:best});
        else if(onProgress)onProgress(best);
      },error=>{
        if(!active)return;
        lastError={code:error.code,message:String(error.message||'').slice(0,240)};
        if(error.code===1)finish({kind:'unavailable',...lastError});
        // A watch may still produce a fix after a transient provider error.
      },{enableHighAccuracy:true,maximumAge:0,timeout:timeoutMs});
      if(!active&&watchId!==null)geolocation.clearWatch(watchId);
    } catch (error) {finish({kind:'unavailable',code:2,message:String(error.message||'').slice(0,240)});}
    return {cancel(){if(!active)return;active=false;clearTimeout(timer);if(watchId!==null)geolocation.clearWatch(watchId);}};
  }
  if(typeof module!=='undefined'&&module.exports)module.exports={requestLocation};
  else root.LunchRunGeoDiagnostics={requestLocation};
})(typeof window!=='undefined'?window:null);
