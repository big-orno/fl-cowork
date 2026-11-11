"""Ouverture automatique du port sur la box (UPnP IGD). Au mieux, sans garantie."""
import re
import socket
import urllib.request
from urllib.parse import urljoin

_SSDP = ('M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\n'
         'MX: 2\r\nST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n\r\n')
_SERVICES = ('urn:schemas-upnp-org:service:WANIPConnection:1',
             'urn:schemas-upnp-org:service:WANIPConnection:2',
             'urn:schemas-upnp-org:service:WANPPPConnection:1')


def _soap(url, service, action, body):
    env = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
           's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
           '<u:%s xmlns:u="%s">%s</u:%s></s:Body></s:Envelope>' % (action, service, body, action))
    req = urllib.request.Request(url, env.encode(), {
        'Content-Type': 'text/xml; charset="utf-8"', 'SOAPAction': '"%s#%s"' % (service, action)})
    return urllib.request.urlopen(req, timeout=4).read().decode('utf-8', 'ignore')


def _gateway(local_ip):
    """(url de controle, service) de la box, ou None."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(2.5)
    try:
        try:
            s.bind((local_ip, 0))
        except OSError:
            pass
        s.sendto(_SSDP.encode(), ('239.255.255.250', 1900))
        data, _ = s.recvfrom(4096)
    except OSError:
        return None
    finally:
        s.close()
    m = re.search(r'(?im)^location:\s*(\S+)', data.decode('utf-8', 'ignore'))
    if not m:
        return None
    try:
        root = m.group(1)
        xml = urllib.request.urlopen(root, timeout=4).read().decode('utf-8', 'ignore')
        for svc in _SERVICES:
            i = xml.find(svc)
            if i < 0:
                continue
            c = re.search(r'<controlURL>([^<]+)</controlURL>', xml[i:])
            if not c:
                continue
            return urljoin(root, c.group(1).strip()), svc
    except Exception:
        return None
    return None


def map_port(local_ip, port, desc='FL Cowork'):
    """Redirige port TCP -> cette machine. Renvoie l'IP publique ou None."""
    gw = _gateway(local_ip)
    if not gw:
        return None
    try:
        _soap(gw[0], gw[1], 'AddPortMapping',
              '<NewRemoteHost></NewRemoteHost><NewExternalPort>%d</NewExternalPort>'
              '<NewProtocol>TCP</NewProtocol><NewInternalPort>%d</NewInternalPort>'
              '<NewInternalClient>%s</NewInternalClient><NewEnabled>1</NewEnabled>'
              '<NewPortMappingDescription>%s</NewPortMappingDescription>'
              '<NewLeaseDuration>0</NewLeaseDuration>' % (port, port, local_ip, desc))
        r = _soap(gw[0], gw[1], 'GetExternalIPAddress', '')
        ip = re.search(r'<NewExternalIPAddress>([\d.]+)<', r)
        return ip.group(1) if ip else None
    except Exception:
        return None


def unmap_port(local_ip, port):
    """Retire la redirection creee par map_port (fin de session)."""
    gw = _gateway(local_ip)
    if not gw:
        return False
    try:
        _soap(gw[0], gw[1], 'DeletePortMapping',
              '<NewRemoteHost></NewRemoteHost><NewExternalPort>%d</NewExternalPort>'
              '<NewProtocol>TCP</NewProtocol>' % port)
        return True
    except Exception:
        return False
