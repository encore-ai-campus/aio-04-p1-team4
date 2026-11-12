// Rebuild the browser bundle after editing app.js or api.js.
const fs=require('fs'),p=__dirname+'/';
fs.writeFileSync(p+'bundle.js',fs.readFileSync(p+'api.js','utf8').replaceAll('export ','')+'\n'+fs.readFileSync(p+'app.js','utf8').replace(/^import.*\r?\n/,''));
