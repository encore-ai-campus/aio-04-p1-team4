import test from 'node:test';
import assert from 'node:assert/strict';
import {phoneUrl} from './network.mjs';
const ipv4=address=>({family:'IPv4',internal:false,address});
test('invite follows the active adapter after Ethernet changes to Wi-Fi',()=>{
  const interfaces={Ethernet:[ipv4('192.168.0.244')]};
  assert.equal(phoneUrl(4174,'',interfaces),'http://192.168.0.244:4174');
  delete interfaces.Ethernet;
  interfaces['Wi-Fi']=[ipv4('192.168.0.17')];
  assert.equal(phoneUrl(4174,'',interfaces),'http://192.168.0.17:4174');
});
test('virtual adapters do not become phone addresses and explicit URLs still work',()=>{
  assert.equal(phoneUrl(4174,'',{'vEthernet (WSL)':[ipv4('172.22.128.1')],'Wi-Fi':[ipv4('10.1.2.3')]}),'http://10.1.2.3:4174');
  assert.equal(phoneUrl(4174,'https://example.com/',{}),'https://example.com');
});
