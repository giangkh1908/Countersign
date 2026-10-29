import os, json, base64, httpx
T="http://127.0.0.1:8080/realms/acme/protocol/openid-connect/token"
def cl(t):
    p=t.split(".")[1]; c=json.loads(base64.urlsafe_b64decode(p+"="*(-len(p)%4)))
    return {k:c.get(k) for k in ("aud","azp","scope","sub","dept","clearance")}
s=os.environ["SPIKE_C_SECRET"]
r=httpx.post(T,data=dict(grant_type="password",client_id="spike-c-nosa",client_secret=s,username="chi.le",password=os.environ["SPIKE_C_PW"]))
print("login", r.status_code, cl(r.json()["access_token"]))
r2=httpx.post(T,data=dict(grant_type="urn:ietf:params:oauth:grant-type:token-exchange",client_id="spike-c-nosa",client_secret=s,subject_token=r.json()["access_token"],subject_token_type="urn:ietf:params:oauth:token-type:access_token",audience="tickets-mcp",scope="tickets:read"))
print("exchange (serviceAccountsEnabled=false)", r2.status_code, cl(r2.json()["access_token"]) if r2.status_code==200 else r2.json())
r3=httpx.post(T,data=dict(grant_type="client_credentials",client_id="spike-c-nosa",client_secret=s,scope="tickets:read"))
print("client_credentials (serviceAccountsEnabled=false)", r3.status_code, r3.json() if r3.status_code!=200 else "TOKEN ISSUED")
