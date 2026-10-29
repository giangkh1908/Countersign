# Spike B - BFF token exchange -> agent-service / approval-signer (M0)

Chung minh bang code chay that tren Keycloak 26.4.7 (realm `acme`): chuoi token BFF(chat-ui) -> agent-service / approval-signer,
mot vong approve + mot vong reject bang LangGraph `interrupt()` + `Command(resume=...)` qua BFF.

## Chay lai

```bash
cd /d/AI_EXAMPLE
uv run --no-project --with fastapi --with uvicorn --with httpx --with "pyjwt[crypto]" --with langgraph   python spikes/b_bff_token_exchange/run_cases.py            # them --no-cleanup de debug
```
Yeu cau: stack Keycloak dang chay (`docker compose`), cong 8310/8311/8312 ranh (override: `SPIKE_B_BFF_PORT`, `SPIKE_B_SIGNER_PORT`, `SPIKE_B_AGENT_PORT`).
`run_cases.py` tu goi `kc_setup.sh snapshot|setup` o dau va `cleanup` o cuoi (trong `finally`). Ghi `output.txt`.
Lenh kc_setup thu cong: `MSYS_NO_PATHCONV=1 docker compose exec -T keycloak bash -s <subcmd> < spikes/b_bff_token_exchange/kc_setup.sh`
(subcmd: snapshot, setup, export, probe-create, probe-enable, probe-delete, cleanup; setup can `SPIKE_B_PW_AN`, `SPIKE_B_PW_BINH`).

## Thay doi Keycloak da lam (tat ca nam trong `kc_setup.sh`)

| Thay doi | Lenh kcadm | Sau cleanup |
|---|---|---|
| Them redirect URI tam `http://localhost:8310/auth/callback` vao chat-ui | `update clients/<id> -s redirectUris[1]=...` | Go; ve dung `["http://localhost:8300/auth/callback"]` |
| Dat mat khau non-temporary (ngau nhien moi lan chay) cho an.nguyen, binh.tran | `set-password --username U --new-password ...` | Xoa credential password; ve `credentials: []` nhu snapshot (truoc do 2 user KHONG co credential nen khong mat gi) |
| requiredActions cua 2 user | khong phai go (da la `[]`) | khong doi |
| Client tam `spike-b-probe` (confidential, serviceAccounts), bat roi xoa `standard.token.exchange.enabled` | `create clients`, `update ... attributes."standard.token.exchange.enabled"=true`, `delete clients/<id>` | Da xoa; `spike_b_clients: ""` |
| Brute-force lockout cua 2 user | `delete attack-detection/brute-force/users/<id>` | Da xoa |

Khong sua chat-ui (ngoai redirect URI tam), approval-signer, agent-service, scope nao. `kc_snapshot_before.json` la trang thai truoc;
phan "STATE AFTER CLEANUP" cuoi output.txt khop snapshot. Khong co thay doi nao "can giu".
Luu y: kc_setup dung file config kcadm rieng `/tmp/kcadm-spikeb.config` (khong de len Spike C).

## Output that

```
versions: {"fastapi": "0.162.0", "uvicorn": "0.54.0", "httpx": "0.28.1", "PyJWT": "2.15.1", "langgraph": "1.2.18", "cryptography": "50.0.2"} python 3.12.14
keycloak.acme.local resolves on host? no -> HostRewrite transport (Host header giu nguyen)
== kc_setup setup ==
added redirect URI http://localhost:8310/auth/callback at index 1
password (non-temporary) set for an.nguyen
requiredActions(an.nguyen) = {"requiredActions":[]}
password (non-temporary) set for binh.tran
requiredActions(binh.tran) = {"requiredActions":[]}
  login token claims: {"aud": "chat-ui", "azp": "chat-ui", "scope": "openid acme-claims aud-chat-ui", "sub": "d6afa1fc-db1a-445f-917a-a6275e593cc3", "dept": ["SALES"], "clearance": 1, "act": "<absent>", "may_act": "<absent>", "sid": "1a566686-8e78-30f8-104d-3af7904eb2a0", "typ": "Bearer", "exp-iat": 300, "iss": "http://keycloak.acme.local:8080/realms/acme", "has_sid": true}
  callback status 302 location / Set-Cookie: ['set-cookie: sid=<sid-value-redacted>; HttpOnly; Path=/; SameSite=strict']
[C1] login qua BFF (code+PKCE S256, scope=openid), aud login token -> aud=chat-ui azp=chat-ui cookie HttpOnly+SameSite=Strict=True  <PASS>
  /api/me keys: ['csrf_token', 'preferred_username', 'sub']
[C1-scan] quet 3 response BFF->trinh duyet (body+header), regex JWT + 1 token that trong session -> 0 hit   <PASS>
  C2a claims: {"aud": "agent-service", "azp": "chat-ui", "scope": "acme-claims aud-chat-ui agent:invoke", "sub": "d6afa1fc-db1a-445f-917a-a6275e593cc3", "dept": ["SALES"], "clearance": 1, "act": "<absent>", "may_act": "<absent>", "sid": "1a566686-8e78-30f8-104d-3af7904eb2a0", "typ": "Bearer", "exp-iat": 300}
[C2a] exchange audience=agent-service scope=agent:invoke -> azp thuc te=chat-ui aud=agent-service chat-ui_in_aud=False act=False  <PASS>
  C2b claims: {"aud": "approval-signer", "azp": "chat-ui", "scope": "signer:approve acme-claims aud-chat-ui", "sub": "d6afa1fc-db1a-445f-917a-a6275e593cc3", "dept": ["SALES"], "clearance": 1, "act": "<absent>", "may_act": "<absent>", "sid": "1a566686-8e78-30f8-104d-3af7904eb2a0", "typ": "Bearer", "exp-iat": 300}
[C2b] exchange audience=approval-signer scope=signer:approve -> azp thuc te=chat-ui aud=approval-signer chat-ui_in_aud=False act=False  <PASS>
[C2c] exchange audience=approval-signer KHONG scope (tham khao) -> HTTP 400 {"error": "invalid_request", "error_description": "Requested audience not available: approval-signer"}  <INFO>
[C2d] exchange gop 2 audience + 2 scope (tham khao) -> HTTP 200 claims={"aud": ["approval-signer", "agent-service"], "azp": "chat-ui", "scope": "signer:approve acme-claims aud-chat-ui agent:invoke", "sub": "d6afa1fc-db1a-445f-917a-a6275e593cc3", "dept": ["SALES"], "clearance": 1, "act": "<absent>", "may_act": "<absent>", "sid": "1a566686-8e78-30f8-104d-3af7904eb2a0", "typ": "Bearer", "exp-iat": 300}  <INFO>
== C2e: kc_setup export ==
== client chat-ui ==
{
  "clientId" : "chat-ui",
  "redirectUris" : [ "http://localhost:8300/auth/callback", "http://localhost:8310/auth/callback" ],
  "attributes" : {
    "realm_client" : "false",
    "standard.token.exchange.enabled" : "true",
    "post.logout.redirect.uris" : "http://localhost:8300/*",
    "pkce.code.challenge.method" : "S256"
  },
  "defaultClientScopes" : [ "aud-chat-ui", "acme-claims" ],
  "optionalClientScopes" : [ "signer:approve", "agent:invoke" ]
}== client agent-service ==
{
  "clientId" : "agent-service",
  "redirectUris" : [ ],
  "attributes" : {
    "realm_client" : "false",
    "standard.token.exchange.enabled" : "true",
    "post.logout.redirect.uris" : "+"
  },
  "defaultClientScopes" : [ "acme-claims" ],
  "optionalClientScopes" : [ "tickets:write", "tickets:read", "llm:invoke", "analytics:read", "docs:read" ]
}
  partial-export attributes: {"agent-service": {"realm_client": "false", "standard.token.exchange.enabled": "true", "post.logout.redirect.uris": "+"}, "chat-ui": {"realm_client": "false", "standard.token.exchange.enabled": "true", "post.logout.redirect.uris": "http://localhost:8300/*", "pkce.code.challenge.method": "S256"}}
  grep token.exchange trong admin-ui jar (khong co unzip trong container -> docker cp + python zipfile tren host):
    attributes.standard.token.exchange.enabled x 3
    standard-token-exchange-enabled x 2
    standardTokenExchangeEnabled x 2
    x.StandardTokenExchangeV2 x 1
    kc-standard-token-exchange-enabled x 1
    standardTokenExchangeEnabledHelp x 1
    e.StandardTokenExchangeV2 x 1
    TOKEN_EXCHANGE_STANDARD_V2 x 1
    Gt.StandardTokenExchangeV2 x 1
    attributes.standard.token.exchange.enableRefreshRequestedTokenType x 1
== probe-attr ==
  before enable: subject=chat-ui login token audience=agent-service -> HTTP 400 invalid_request: Standard token exchange is not enabled for the requested client
  before enable: subject=probe own client_credentials token audience=agent-service -> HTTP 400 invalid_request: Standard token exchange is not enabled for the requested client
  kc_setup probe-enable: enabled
  after enable: subject=chat-ui login token audience=agent-service -> HTTP 403 access_denied: Client is not within the token audience
  after enable: subject=probe own client_credentials token audience=agent-service -> HTTP 400 invalid_request: Requested audience not available: agent-service
  kc_setup probe-delete: ['deleted spike-b-probe']
[C2e] ten attribute that duoc server ton trong (probe spike-b-probe) -> xem '== probe-attr ==' o tren  <PASS>
[C3i] signer: token (b) cua an + intent sub=an -> HTTP 200  <PASS>
[C3ii] signer: token (a) aud=agent-service -> HTTP 401 {"error":"invalid_audience","detail":"aud=agent-service khong chua approval-signer"}  <PASS>
[C3iii] signer: token dang nhap aud=chat-ui -> HTTP 401 {"error":"invalid_audience","detail":"aud=chat-ui khong chua approval-signer"}  <PASS>
[C3iv] signer: binh.tran (token b cua binh) ky intent cua an -> HTTP 403 {"error":"sub_mismatch","detail":"token.sub != intent.sub"}  <PASS>
[C5a-1] POST /api/chat -> interrupt payload -> HTTP 200 intent={"intent_id": "2e43208d94404813b1ded1762ebcb713", "sub": "d6afa1fc-db1a-445f-917a-a6275e593cc3", "op": "tickets.close", "target": "TCK-1001", "args": {"resolution": "fixed", "note": "dong ticket TCK-1001"}, "exp": 1793292427}  <PASS>
[C5a] approve -> executed -> HTTP 200 {"thread_id":"c87f4311436b49e98b4aefcf15e994cb","status":"executed","reason":null}  <PASS>
[C5b] reject -> rejected (khong thuc thi) -> HTTP 200 {"thread_id":"be117ea6849d441b9e873701287f0ccc","status":"rejected","reason":null}  <PASS>
[C5c] resume truc tiep bang JWS bi sua (reject->approve, giu chu ky) -> HTTP 200 {"thread_id":"fcd5a71220864600afe43f248590b405","status":"refused","reason":"InvalidSignatureError: Signature verification failed"}  <PASS>
[C5d] resume bang JWS hop le cua intent KHAC (hash lech) -> HTTP 200 {"thread_id":"7236062ad0514b4291690fc06ca9dbe2","status":"refused","reason":"ValueError: intent_sha256 lech"}  <PASS>
[C5e] POST /api/approvals thieu X-CSRF-Token -> HTTP 403  <PASS>
[C5f] (them) binh.tran approve thread cua an qua BFF cua binh -> HTTP 404 {"error":"unknown_thread_or_intent"}  <PASS>
  token agent da nhan/luu: {"aud": "agent-service", "azp": "chat-ui", "scope": "acme-claims aud-chat-ui agent:invoke", "sub": "d6afa1fc-db1a-445f-917a-a6275e593cc3", "dept": ["SALES"], "clearance": 1, "act": "<absent>", "may_act": "<absent>", "sid": "1a566686-8e78-30f8-104d-3af7904eb2a0", "typ": "Bearer", "exp-iat": 300} == token (a) cua session: True
[C4i] agent-service exchange audience=approval-signer scope=signer:approve -> tu choi: HTTP 400 {"error": "invalid_scope", "error_description": "Invalid scopes: signer:approve"}  <PASS>
[C4ii] agent-service exchange audience=approval-signer (khong scope) -> tu choi: HTTP 400 {"error": "invalid_request", "error_description": "Requested audience not available: approval-signer"}  <PASS>
[C4iii] agent-service exchange scope=signer:approve (khong audience) -> tu choi: HTTP 400 {"error": "invalid_scope", "error_description": "Invalid scopes: signer:approve"}  <PASS>
[C4c] doi chung: agent-service exchange audience=llm-gateway scope=llm:invoke -> HTTP 200 claims={"aud": "llm-gateway", "azp": "agent-service", "scope": "acme-claims llm:invoke", "sub": "d6afa1fc-db1a-445f-917a-a6275e593cc3", "dept": ["SALES"], "clearance": 1, "act": "<absent>", "may_act": "<absent>", "sid": "1a566686-8e78-30f8-104d-3af7904eb2a0", "typ": "Bearer", "exp-iat": 300}  <PASS>
  token llm-gateway goi signer -> 401 {"error":"invalid_audience","detail":"aud=llm-gateway khong chua approval-signer"}
[C1b] quet 25 response BFF->trinh duyet (body+header), regex JWT + 5 token that trong session -> 0 hit   <PASS>
== kc_setup cleanup ==
redirectUris restored -> ["http://localhost:8300/auth/callback"]
deleted password credential of an.nguyen (khong khoi phuc duoc mat khau cu neu truoc do co)
cleared brute-force lockout of an.nguyen
deleted password credential of binh.tran (khong khoi phuc duoc mat khau cu neu truoc do co)
cleared brute-force lockout of binh.tran
== STATE AFTER CLEANUP ==
{
"chat-ui": {  "clientId" : "chat-ui",  "redirectUris" : [ "http://localhost:8300/auth/callback" ],  "attributes" : {    "realm_client" : "false",    "standard.token.exchange.enabled" : "true",    "post.logout.redirect.uris" : "http://localhost:8300/*",    "pkce.code.challenge.method" : "S256"  }},
"approval-signer": {  "clientId" : "approval-signer",  "enabled" : true,  "bearerOnly" : true,  "standardFlowEnabled" : false,  "serviceAccountsEnabled" : false,  "publicClient" : false,  "attributes" : {    "realm_client" : "false",    "post.logout.redirect.uris" : "+"  },  "defaultClientScopes" : [ ],  "optionalClientScopes" : [ ]},
"an.nguyen": {"id": "d6afa1fc-db1a-445f-917a-a6275e593cc3",
"user": {  "username" : "an.nguyen",  "emailVerified" : true,  "enabled" : true,  "requiredActions" : [ ]},
"credentials": [ ]}
,
"binh.tran": {"id": "3d1d7eef-f56b-4ba1-af45-b89370c96adf",
"user": {  "username" : "binh.tran",  "emailVerified" : true,  "enabled" : true,  "requiredActions" : [ ]},
"credentials": [ ]}
,
"spike_b_clients": ""
}
SUMMARY
  C1: PASS
  C1-scan: PASS
  C2a: PASS
  C2b: PASS
  C2c: INFO
  C2d: INFO
  C2e: PASS
  C3i: PASS
  C3ii: PASS
  C3iii: PASS
  C3iv: PASS
  C5a-1: PASS
  C5a: PASS
  C5b: PASS
  C5c: PASS
  C5d: PASS
  C5e: PASS
  C5f: PASS
  C4i: PASS
  C4ii: PASS
  C4iii: PASS
  C4c: PASS
  C1b: PASS
ALL PASS
```

## Ghi chu ky thuat

- **Hostname**: may host khong resolve `keycloak.acme.local` (ping fail). `iss` token = `http://keycloak.acme.local:8080/realms/acme`, nhung
  Keycloak van phuc vu qua `localhost:8080`. "Trinh duyet" (httpx.Client) dung transport `HostRewrite` noi `keycloak.acme.local`/`localhost` toi
  127.0.0.1 nhung GIU header Host. BFF redirect trinh duyet toi authorization endpoint o `keycloak.acme.local:8080` (URL cong khai), con goi
  server->server (token, JWKS, exchange) di qua `localhost:8080`.
- **Bug da gap**: lan dau transport sua `request.url` tai ccho -> cookie jar luu cookie Keycloak theo 127.0.0.1 -> POST form login bao
  "Restart login cookie not found" (400). Sua: tao `httpx.Request` MOI trong transport, de request goc (theo do jar tinh domain) khong doi.
- **Cookie phien**: `sid` (HttpOnly, SameSite=Strict, khong Secure) khi BFF chay http; `__Host-sid` + Secure khi https (xem comment trong `bff.py`).
- `httpx.post(data=[(k,v),...])` (list tuple, can cho audience lap) khong con duoc ho tro o httpx 0.28 -> dung `content=urlencode(...)`.
- Khong co `unzip`/`jar`/`python` trong container Keycloak: jar admin-ui duoc `docker compose cp` ra thu muc tam roi doc bang `zipfile` tren host.
- `kcadm get --fields attributes` tra `{}`; phai dung `--fields 'attributes(*)'`. Khong co `--exact` cho `get users`; dung `-q exact=true`.
- Keycloak khong tra `act` (khong co delegation) va khong them `may_act`; `sid` cua token exchange giu nguyen sid cua phien dang nhap.
- `uvicorn` goi `sys.stdout.isatty()` -> lop Tee phai co `isatty()`.
- Phan "harness" doc `bff.SESSIONS` / `agent.LAST_BEARER` truc tiep (cung process) de lay token cho C2-C5 va de quet ro ri; day la cua ban test, khong phai API.
- Phien ban: fastapi 0.162.0, uvicorn 0.54.0, httpx 0.28.1, PyJWT 2.15.1, langgraph 1.2.18, cryptography 50.0.2, Python 3.12.14; Keycloak 26.4.7.

## Kết luận (lead review)

**Verdict chung: ĐẠT, giữ phương án chính.** Lead đã review code `signer.py`/`agent.py`/`bff.py`, tự chạy lại kiểm tra Keycloak sau cleanup
(redirectUris chỉ còn `:8300`, 0 credential cho an.nguyen/binh.tran, không còn client `spike-b-*`) và quét repo: không có JWT hay nội dung secret.

| # | Tiêu chí | Verdict | Bằng chứng (output.txt) |
|---|---|---|---|
| 1 | Login code + PKCE S256, token đăng nhập chỉ `aud=chat-ui`, session server-side, token không xuống trình duyệt | **ĐẠT** | C1: `aud=chat-ui`, `azp=chat-ui`, `scope=openid acme-claims aud-chat-ui`; cookie `sid` HttpOnly + SameSite=Strict; C1b quét 25 response BFF -> 0 JWT, 0 token thật |
| 2 | Hai exchange riêng `agent-service`/`approval-signer`; `azp`; tên attribute | **ĐẠT** | C2a `aud=agent-service`, C2b `aud=approval-signer`; cả hai `azp=chat-ui`, không `act`/`may_act`, `chat-ui` KHÔNG còn trong `aud`, `sid` giữ nguyên, TTL 300s. Attribute thật `standard.token.exchange.enabled` (export + admin-ui jar + probe đổi lỗi) |
| 3 | Signer kiểm `aud`, `azp==chat-ui`, `sub==intent.sub`; token `aud=agent-service` bị chặn | **ĐẠT** | C3i 200; C3ii 401 `invalid_audience` (chính token agent cầm); C3iii 401; C3iv 403 `sub_mismatch` |
| 4 | `agent-service` exchange sang signer bị Keycloak từ chối | **ĐẠT** | C4i/C4iii 400 `invalid_scope: Invalid scopes: signer:approve`; C4ii 400 `invalid_request: Requested audience not available: approval-signer`; đối chứng C4c (`llm-gateway`) 200 |
| 5 | Một vòng approve + một vòng reject qua `interrupt()`/`Command(resume=...)` | **ĐẠT** | C5a `executed`, C5b `rejected`; C5c JWS bị sửa -> `refused`; C5d hash lệch -> `refused`; C5e thiếu CSRF -> 403; C5f user khác -> 404 |
| 6 | Phương án B | **Không kích hoạt** | Phương án chính đạt hết. Đánh giá ở dưới |

**Phát hiện**
1. `azp` sau exchange V2 = **client gửi request** (`chat-ui` với C2a/b, `agent-service` với C4c). Kiểm `azp == chat-ui` ở signer có ý nghĩa.
   Lưu ý: không có cách hợp lệ nào lấy được token `aud=approval-signer` với `azp != chat-ui`, nên nhánh 403 `invalid_azp` chỉ là phòng thủ chiều sâu, chưa bị bắn bởi token thật.
2. Tham số `audience` **lọc** audience: token exchange KHÔNG mang `aud=chat-ui` dù `scope` vẫn ghi `aud-chat-ui`. Thiếu optional scope thì lỗi `Requested audience not available` (C2c).
3. **Gộp hai audience trong MỘT request vẫn thành công** (C2d: `aud=["approval-signer","agent-service"]`). Keycloak không chặn được việc này, nên việc tách hai request là trách nhiệm code BFF: cần test hồi quy ở BFF.
   Tương tự, nếu BFF xin `scope=openid agent:invoke ...` lúc login thì token đăng nhập sẽ mang luôn các aud đó. BFF phải login với `scope=openid` (chưa chạy thử, suy ra từ luật default/optional scope).
4. Mã lỗi Keycloak khác tài liệu: F22b (`05-approval-flow.md:499`) ghi `403 access_denied/invalid_client`, thực tế là **400 `invalid_scope`** (khi có `scope`) hoặc **400 `invalid_request`** (chỉ `audience`).
   Client không nằm trong `aud` của subject token thì nhận **403 `access_denied: Client is not within the token audience`** (probe). Test nên assert "4xx, không có `access_token`" cộng với `error ∈ {invalid_scope, invalid_request, access_denied}`.
5. V2 không phát `act`. Ví dụ JSON ở `00-contracts.md:398` có `"act":{"sub":"agent-service"}` là sai với thực tế, cần bỏ.
6. Cookie: chạy http localhost thì dùng `sid` (không Secure). Lý do: `__Host-` bắt buộc Secure, và cookie jar (httpx/http.cookiejar) không gửi cookie Secure qua http. Cách này khớp D15 ("dev http dùng `sid`").
7. Hạ tầng: host không resolve `keycloak.acme.local`. Redirect trình duyệt trỏ về hostname này, nên E2E/Playwright ở M1 cần mục hosts hoặc `--host-resolver-rules`.
8. Signer của spike chưa kiểm `scope ∋ signer:approve` (05 có yêu cầu) và agent chưa chống replay `jti`. Hai việc này để lại cho M1, không ảnh hưởng kết luận.

**Phương án B (đánh giá, không dùng).** ROADMAP:56 định nghĩa B là "BFF dùng client-credentials + header user token đã verify",
còn `04-infra-data-eval.md:1149` lại định nghĩa B là `self_signed_sts` (agent tự ký). Hai định nghĩa không thống nhất.
Với spike B, phương án B hợp lý sẽ là: signer nhận token client-credentials của `chat-ui` (service account, `azp=chat-ui`) kèm header token đăng nhập của user, rồi tự verify cả hai.
Cách này vẫn chặn được agent vì agent không có secret `chat-ui`. Đổi lại phải bật service account cho `chat-ui`, token đăng nhập rời BFF sang signer, và signer phải tự ghép danh tính.
Vì phương án chính đã đạt, không cần B. Đề xuất chốt một định nghĩa B duy nhất trong 04 §4.3.

## Đề xuất realm-acme.json (chỉ đề xuất, chưa sửa file)

Cấu hình hiện tại **đã đúng và đủ** cho luồng D15. Không có thay đổi bắt buộc. Đề xuất giữ nguyên các điểm đã được xác minh và thêm hai chỉnh sửa nhỏ, tuỳ chọn:

```diff
@@ clientScopes: "aud-chat-ui"
-  "attributes": { "include.in.token.scope": "true", "display.on.consent.screen": "false" },
+  "attributes": { "include.in.token.scope": "false", "display.on.consent.screen": "false" },
@@ clientScopes: "acme-claims"
-  "attributes": { "include.in.token.scope": "true", "display.on.consent.screen": "false" },
+  "attributes": { "include.in.token.scope": "false", "display.on.consent.screen": "false" },
```
Lý do: token exchange hiện có `scope="acme-claims aud-chat-ui agent:invoke"`. Tên scope kỹ thuật lọt vào claim `scope`, trong khi `aud` thật không chứa `chat-ui`, nên dễ đọc nhầm.
Sau chỉnh, `scope` chỉ còn `agent:invoke` hoặc `signer:approve`. **Chưa chạy thử.** Cần xác nhận mapper vẫn áp dụng khi `include.in.token.scope=false` (theo tài liệu Keycloak thì có).

Giữ nguyên (đã xác minh):
- `chat-ui.attributes."standard.token.exchange.enabled": "true"` và `agent-service` tương tự. Tên attribute đúng.
- `signer:approve` chỉ là optional scope của `chat-ui`, **không** gán cho `agent-service`, không nằm trong realm default scopes. Đây là cơ chế chặn C4.
- `approval-signer` để `bearerOnly`, không bật exchange.

Ngoài realm (đề xuất cho file khác):
- `04-infra-data-eval.md:1143` bỏ `--features=token-exchange-standard` (V2 mặc định bật), bỏ "[cần xác minh]" cho tên attribute.
- `05-approval-flow.md:499` sửa mã lỗi F22b như phát hiện 4.
- `00-contracts.md:398` bỏ `act`.
- Nâng Keycloak lên 26.8.1 (CVE-2026-97846) ở `docker-compose.yml` (research/05).

## Đề xuất ADR

**ADR-005: Chuỗi token BFF bằng Keycloak Standard Token Exchange V2, tách audience theo request**
- *Trạng thái:* Đề xuất (dựa trên Spike B, Keycloak 26.4.7).
- *Bối cảnh:* D13/D15 yêu cầu agent (giả định có thể bị chiếm) không bao giờ cầm được token dùng cho `approval-signer`. Thiết kế dựa trên ba giả định chưa kiểm: `azp` sau exchange, việc `audience` lọc hay thêm, và Keycloak có chặn `agent-service` hay không.
- *Quyết định:*
  1. BFF (client `chat-ui`, confidential, PKCE S256) login với `scope=openid`. Token đăng nhập chỉ có `aud=chat-ui` và không rời BFF.
  2. BFF gọi **hai request exchange riêng** (RFC 8693, V2): `audience=agent-service&scope=agent:invoke` gửi cho agent mỗi request; `audience=approval-signer&scope=signer:approve` chỉ giữ trong session server-side, TTL ≤ 300s. Cấm gộp audience.
  3. Quyền tới audience được kiểm soát **duy nhất bằng thiết kế client scope**: optional scope + audience mapper. Không dùng client policy hay fine-grained permission.
  4. Signer kiểm `aud ∋ approval-signer`, `azp == chat-ui`, `scope ∋ signer:approve`, `sub == intent.sub`. Không dựa vào `act`, vì V2 không phát claim này.
  5. Phương án B, chỉ dùng khi nâng cấp Keycloak làm hỏng V2: client-credentials của `chat-ui` kèm token user đã verify. Ghi rõ giới hạn.
- *Hệ quả:*
  - (+) Không cần plugin hay feature preview. Agent bị chặn ở hai lớp: Keycloak `invalid_scope` và signer `aud`/`azp`.
  - (−) Mỗi phiên tốn thêm hai lần gọi Keycloak; việc tách request là kỷ luật của code BFF (cần test hồi quy cho C2d).
  - (−) Mỗi lần đổi realm phải chạy lại suite F22/F22b. Test assert mã lỗi 4xx theo phát hiện 4.
  - (−) Thiếu `act` nên audit chuỗi uỷ quyền phải dựa vào `azp` + `sid`.
