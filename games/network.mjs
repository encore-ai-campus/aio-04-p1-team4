import os from 'node:os';

// Resolve on each request: switching Ethernet/Wi-Fi can change the invite address.
export function phoneUrl(port, override=process.env.PUBLIC_URL, interfaces=os.networkInterfaces()) {
  if (override) return override.replace(/\/+$/, '');
  const addresses=Object.entries(interfaces)
    .filter(([name])=>! /vEthernet|WSL|Hyper-V|Loopback/i.test(name))
    .flatMap(([,items])=>items||[])
    .filter(a=>(a.family==='IPv4'||a.family===4)&&!a.internal)
    .map(a=>a.address);
  const ip=addresses.find(x=>x.startsWith('192.168.'))||addresses.find(x=>x.startsWith('10.'))||addresses[0]||'127.0.0.1';
  return `http://${ip}:${port}`;
}
