"""
A low-level, general abstraction for the LG SmartThinQ API.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
import re
import ssl
import sys
from typing import Any
from urllib.parse import (
    parse_qs,
    quote,
    urlencode,
    urljoin,
    urlparse,
)
import uuid

import aiohttp
from charset_normalizer import from_bytes
import xmltodict

from . import core_exceptions as exc
from .const import DEFAULT_COUNTRY, DEFAULT_LANGUAGE, DEFAULT_TIMEOUT
from .core_util import add_end_slash, as_list, gen_uuid
from .device_info import KEY_DEVICE_ID, DeviceInfo

# The core version
CORE_VERSION = "coreAsync"

ENABLE_CLEANUP_CLOSED = not (3, 11, 1) <= sys.version_info < (3, 11, 4)
# Enabling cleanup closed on python 3.11.1+ leaks memory relatively quickly
# see https://github.com/aio-libs/aiohttp/issues/7252
# aiohttp interacts poorly with https://github.com/python/cpython/pull/98540
# The issue was fixed in 3.11.4 via https://github.com/python/cpython/pull/104485

# v2
V2_API_KEY = "VGhpblEyLjAgU0VSVklDRQ=="
V2_NSCREEN_API_KEY = "ijVUYQIKVVaLNpfZrLOI2CeWrYlrAkImRFbGvIRQFrf3qjUhWLOgbxvtICtr1OiC"
# V2_CLIENT_ID = "65260af7e8e6547b51fdccf930097c51eb9885a508d3fddfa9ee6cdec22ae1bd"
V2_CLIENT_ID = "c713ea8e50f657534ff8b9d373dfebfc2ed70b88285c26b8ade49868c0b164d9"
V2_SVC_PHASE = "OP"
V2_APP_LEVEL = "PRD"
V2_APP_OS = "browser"
V2_APP_TYPE = "WEB"
V2_APP_VER = "5.1.2600"
V2_THINQ_APP_VER = "LG ThinQ/5.0.12120"
V2_APP_ORIGIN = "app-web-browser"
V2_WEB_REFERER = "https://my.lgthinq.com/"
V2_WEB_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
V2_CLIENT_ID_REFRESH_INTERVAL = 60 * 60

# new
V2_GATEWAY_URL = "https://route.lgthinq.com:46030/v1/service/application/gateway-uri"
V2_GATEWAY_URI_KEY = "uris"
V2_NSCREEN_AUTH_REFRESH_URL = "https://kic-nscreen.lgthinq.com/v1/auth/refresh"
V2_NSCREEN_AUTH_LOGIN_URL = "https://kic-nscreen.lgthinq.com/v1/auth/login"
V2_WEB_USER_INFO_URL = (
    "https://kr.lid.lgemembers.com/realms/LGE-MP/"
    "protocol/lge-openid-connect/userinfo"
)
V2_WEB_SIGNIN_ACT_URL = "https://kr.lgemembers.com/lgacc/front/v1/signin/signInAct"
V2_WEB_KC_CODE_URL = "https://kr.lgemembers.com/lgacc/service/v1/keycloak/kcCode"
V2_WEB_POST_SIGNIN_TOKEN_RE = (
    r"setSessionStorageObject\('post_signin_token', '([^']+)'\)"
)
V2_WEB_USER_INFO_LEGACY_URL = (
    "https://kr.lgemembers.com/lgacc/service/v1/keycloak/userInfo"
)
V2_WEB_SEARCH_USER_NO_URL = (
    "https://kr.lgemembers.com/lgacc/front/v1/signin/searchByUserNo"
)
V2_WEB_SIGNIN_COMPLETE_URL = (
    "https://kr.lgemembers.com/lgacc/front/v1/signin/signInComplete"
)
V2_WEB_DECRYPT_TOKEN_URL = (
    "https://kr.lgemembers.com/lgacc/service/v1/keycloak/decryptTokenUrl"
)
V2_WEB_LOGIN_PUBLIC_KEY = b"""-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAkb2bcfvV5Q2Ag0UI6Mj3
oDmS0b2I9RTIRFhIVqrO47FRKQaFQpjiKkgxMcbLqK+ACTORrt6eA6srX/HKGtN9
aJvM/8ZzqAe1tztli/yQtm6MezKExTtSAxYkawaV2s+pj7RkOes+BsJ0ahL/HC1x
divxU4M0DN7AKdOyQM3XJnAfIimb1yhI5VeQkSBLDeAY9OTjRdAn4N6aRXaIwtck
hQYDs7t120uhRvtRX8WVY+YiROCKTgK9PPcvaGgWublxLnSPFFb4BGYDan2Ro0DL
b0DD1It4vqePBDWZD9MByhRJ67mQGXOJ/u3EEbctHB7TZkejjWn5sArU6K1jP0LB
hwIDAQAB
-----END PUBLIC KEY-----"""

# orig
DATA_ROOT = "lgedmRoot"
SECURITY_KEY = "nuts_securitykey"
SVC_CODE = "SVC202"

API2_ERRORS = {
    "0101": exc.DeviceNotFound,
    "0102": exc.NotLoggedInError,
    "0106": exc.NotConnectedError,
    "0100": exc.FailedRequestError,
    "0110": exc.InvalidCredentialError,
    "0111": exc.DelayedResponseError,
    9000: exc.InvalidRequestError,  # Surprisingly, an integer (not a string).
    "9006": exc.UseOfficialAPIError,
    "9012": exc.UseOfficialAPIError,
    "9995": exc.FailedRequestError,  # This come as "other errors", we manage as not FailedRequestError.
    "9999": exc.FailedRequestError,  # This come as "other errors", we manage as not FailedRequestError.
}

DEFAULT_TOKEN_VALIDITY = 3600  # seconds
TOKEN_EXP_LIMIT = 60  # will expire within 60 seconds

# minimum time between 2 consecutive call for device snapshot updates (in seconds)
MIN_TIME_BETWEEN_UPDATE = 25

_LG_SSL_CIPHERS = (
    "DEFAULT:!aNULL:!eNULL:!MD5:!3DES:!DES:!RC4:!IDEA:!SEED:!aDSS:!SRP:!PSK"
)

_COMMON_LANG_URI_ID = "langPackCommonUri"
_LOCAL_LANG_FILE = "local_lang_pack.json"

_API_USE_HOMES = False
_HOME_ID = "homeId"
_HOME_NAME = "homeName"
_HOME_CURRENT = "currentHomeYn"

_LOGGER = logging.getLogger(__name__)

def _create_lg_ssl_context() -> ssl.SSLContext:
    """Create a SSL context for LG ThinQ."""
    context = ssl.create_default_context()
    context.set_ciphers(_LG_SSL_CIPHERS)
    return context


_SSL_CONTEXT = _create_lg_ssl_context()


def lg_client_session() -> aiohttp.ClientSession:
    """Create an aiohttp client session to use with LG ThinQ."""
    connector = aiohttp.TCPConnector(
        enable_cleanup_closed=ENABLE_CLEANUP_CLOSED, ssl_context=_SSL_CONTEXT
    )
    return aiohttp.ClientSession(connector=connector)


class CoreAsync:
    """Class for Core SmartThinQ Api async calls."""

    def __init__(
        self,
        country: str = DEFAULT_COUNTRY,
        language: str = DEFAULT_LANGUAGE,
        *,
        timeout: int = DEFAULT_TIMEOUT,
        session: aiohttp.ClientSession | None = None,
        client_id: str | None = None,
        client_id_created_on: datetime | None = None,
        update_clientid_callback: Callable[[str, datetime], None] | None = None,
    ):
        """
        Create the CoreAsync object

        Parameters:
            country: ThinQ account country
            language: ThinQ account language
            timeout: the http timeout (default = 15 sec.)
            session: the AioHttp session to use (if None a new session is created)
        """

        self._country = country
        self._language = language
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._client_id = client_id
        self._client_id_created_on = client_id_created_on
        if self._client_id is not None and self._client_id_created_on is None:
            self._client_id_created_on = datetime.fromtimestamp(0, timezone.utc)
        self._update_clientid_callback = update_clientid_callback
        self._lang_pack_url = None

        if session:
            self._session = session
            self._managed_session = False
        else:
            self._session = None
            self._managed_session = True

    @property
    def country(self) -> str:
        """Return the used country."""
        return self._country

    @property
    def language(self) -> str:
        """Return the used language."""
        return self._language

    @property
    def lang_pack_url(self):
        """Return the used language."""
        return self._lang_pack_url

    @property
    def client_id(self) -> str | None:
        """Return the associated client_id."""
        return self._client_id

    @property
    def client_id_created_on(self) -> datetime | None:
        """Return when the associated client_id was created."""
        return self._client_id_created_on

    async def close(self):
        """Close the managed session on exit."""
        if self._managed_session and self._session:
            await self._session.close()
            self._session = None

    def _get_session(self) -> aiohttp.ClientSession:
        """Return current aiohttp client session or init a new one when required."""
        if not self._session:
            self._session = lg_client_session()
        return self._session

    def _get_client_id(
        self, user_number: str | None = None, force_refresh: bool = False
    ) -> str:
        """Generate a new clent ID or return existing."""
        if (
            self._client_id is not None
            and not force_refresh
            and user_number is not None
            and self._client_id_created_on is not None
        ):
            client_id_age = (
                datetime.now(timezone.utc) - self._client_id_created_on
            ).total_seconds()
            if client_id_age >= V2_CLIENT_ID_REFRESH_INTERVAL:
                _LOGGER.info(
                    "Refreshing client ID after %.0f seconds", client_id_age
                )
                force_refresh = True

        if self._client_id is not None and not force_refresh:
            return self._client_id
        if user_number is None:
            return self._client_id

        hash_object = hashlib.sha256()
        hash_object.update(
            (user_number + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")).encode(
                "utf8"
            )
        )
        self._client_id = hash_object.hexdigest()
        self._client_id_created_on = datetime.now(timezone.utc)
        if self._update_clientid_callback is not None:
            self._update_clientid_callback(self._client_id, self._client_id_created_on)
        return self._client_id

    def _web_client_id(self) -> str:
        """Return a ThinQ Web-style client ID."""
        return self._get_client_id("web") or V2_CLIENT_ID

    @staticmethod
    async def _get_json_resp(response: aiohttp.ClientResponse) -> dict:
        """Try to get the json content from request response."""

        # first, we try to get the response json content
        try:
            return await response.json()
        except ValueError as ex:
            resp_text = await response.text(errors="replace")
            _LOGGER.debug("Error decoding json response %s: %s", resp_text, ex)

        # if fails, we try to convert text from xml to json
        try:
            return xmltodict.parse(resp_text)
        except Exception:
            raise exc.InvalidResponseError(resp_text) from None

    @staticmethod
    def _thinq2_headers(
        extra_headers: dict | None = None,
        client_id: str | None = None,
        access_token: str | None = None,
        user_number: str | None = None,
        country=DEFAULT_COUNTRY,
        language=DEFAULT_LANGUAGE,
        security_key=False,
    ) -> dict:
        """Prepare API2 header."""

        headers = {
            "Accept": "application/json",
            "Content-type": "application/json;charset=UTF-8",
            "x-api-key": V2_API_KEY,
            # "x-app-version": V2_THINQ_APP_VER,
            "x-client-id": client_id or V2_CLIENT_ID,
            "x-country-code": country,
            "x-language-code": language,
            "x-message-id": gen_uuid(),
            "x-service-code": SVC_CODE,
            "x-service-phase": V2_SVC_PHASE,
            "x-origin": V2_APP_ORIGIN,
            "x-thinq-app-level": V2_APP_LEVEL,
            "x-thinq-app-logintype": "LGE" if access_token else "undefined",
            "x-thinq-app-os": V2_APP_OS,
            "x-thinq-app-type": V2_APP_TYPE,
            "x-thinq-app-ver": V2_APP_VER,
            "Referer": V2_WEB_REFERER,
            "User-Agent": V2_WEB_USER_AGENT,
        }

        if security_key:
            headers["x-thinq-security-key"] = SECURITY_KEY

        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        if user_number:
            headers["x-user-no"] = user_number

        add_headers = extra_headers or {}
        return {**headers, **add_headers}

    async def http_get_bytes(
        self,
        url: str,
    ) -> bytes:
        """Make a generic HTTP request."""
        async with self._get_session().get(
            url=url,
            timeout=self._timeout,
        ) as resp:
            result = await resp.content.read()

        return result

    async def thinq2_get(
        self,
        url: str,
        access_token: str | None = None,
        user_number: str | None = None,
        headers: dict | None = None,
    ) -> dict:
        """Make an HTTP request in the format used by the API2 servers."""

        _LOGGER.debug("thinq2_get before: %s", url)

        client_id = self._get_client_id(user_number)
        async with self._get_session().get(
            url=url,
            headers=self._thinq2_headers(
                client_id=client_id,
                access_token=access_token,
                user_number=user_number,
                extra_headers=headers or {},
                country=self._country,
                language=self._language,
            ),
            timeout=self._timeout,
            raise_for_status=False,
        ) as resp:
            out = await self._get_json_resp(resp)

        _LOGGER.debug("thinq2_get after: %s", out)

        if "resultCode" not in out:
            raise exc.APIError("-1", out)

        return self._manage_lge_result(out, True, user_number)

    async def lgedm2_post(
        self,
        url: str,
        data: dict | None = None,
        access_token: str | None = None,
        user_number: str | None = None,
        headers: dict | None = None,
        is_api_v2=False,
    ) -> dict:
        """Make an HTTP request in the format used by the API servers."""

        _LOGGER.debug("lgedm2_post before: %s", url)

        client_id = self._get_client_id(user_number)
        async with self._get_session().post(
            url=url,
            json=data if is_api_v2 else {DATA_ROOT: data},
            headers=self._thinq2_headers(
                client_id=client_id,
                access_token=access_token,
                user_number=user_number,
                extra_headers=headers or {},
                country=self._country,
                language=self._language,
                security_key=True,
            ),
            timeout=self._timeout,
            raise_for_status=False,
        ) as resp:
            out = await self._get_json_resp(resp)

        _LOGGER.debug("lgedm2_post after: %s", out)

        return self._manage_lge_result(out, is_api_v2, user_number)

    def _manage_lge_result(
        self, result: dict, is_api_v2=False, user_number: str | None = None
    ) -> dict:
        """Manage the result from a get or a post to lge server."""

        if is_api_v2:
            if "resultCode" in result:
                code = result["resultCode"]
                if code != "0000":
                    if code in ("9006", "9012"):
                        # we refresh the client_id as work-around for messages
                        # suggesting the official/native API.
                        _LOGGER.info(
                            "Refreshing client ID after receiving msg 9006 or 9012: %s",
                            result,
                        )
                        self._get_client_id(user_number, True)
                    message = result.get("result") or "ThinQ APIv2 error"
                    if code in API2_ERRORS:
                        raise API2_ERRORS[code](message)
                    raise exc.APIError(message, code)

            return result.get("result")

        msg = result.get(DATA_ROOT)
        if not msg:
            raise exc.APIError("-1", result)

        if "returnCd" in msg:
            code = msg["returnCd"]
            if code != "0000":
                message = msg.get("returnMsg") or "ThinQ APIv1 error"
                if code in API2_ERRORS:
                    raise API2_ERRORS[code](message)
                raise exc.APIError(message, code)

        return msg

    async def gateway_info(self):
        """Return ThinQ gateway information."""
        result = await self.thinq2_get(V2_GATEWAY_URL)
        _LOGGER.debug("GatewayV2 info: %s", result)
        if isinstance(result, dict):
            lang_pack = None
            if uris := result.get(V2_GATEWAY_URI_KEY):
                if isinstance(uris, dict):
                    lang_pack = uris.get(_COMMON_LANG_URI_ID)
            if not lang_pack:
                lang_pack = result.get(_COMMON_LANG_URI_ID)
            if lang_pack and self._lang_pack_url is None:
                self._lang_pack_url = lang_pack
                _LOGGER.debug("Common lang pack url: %s", self._lang_pack_url)

        return result

    @staticmethod
    def _web_form_headers(referer: str) -> dict:
        """Return headers used by the ThinQ Web LG account form posts."""
        return {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://kr.lgemembers.com",
            "Referer": referer,
            "User-Agent": V2_WEB_USER_AGENT,
            "X-Requested-With": "XMLHttpRequest",
        }

    @staticmethod
    async def _web_encrypted_user_id(username: str) -> str:
        """Encrypt the LG account user id in the same way as ThinQ Web."""

        def _encrypt() -> str:
            from cryptography.hazmat.primitives.asymmetric import padding
            from cryptography.hazmat.primitives.serialization import (
                load_pem_public_key,
            )

            public_key = load_pem_public_key(V2_WEB_LOGIN_PUBLIC_KEY)
            encrypted = public_key.encrypt(username.encode("utf8"), padding.PKCS1v15())
            return quote(base64.b64encode(encrypted).decode(), safe="")

        return await asyncio.to_thread(_encrypt)

    async def web_user_login(self, username: str, password: str) -> dict:
        """Login through the ThinQ Web flow and return auth information."""
        session = self._get_session()
        login_headers = self._thinq2_headers(
            client_id=self._web_client_id(),
            country=self._country,
            language=self._language,
            extra_headers={
                "x-api-key": V2_NSCREEN_API_KEY,
                "x-origin": "webapp",
            },
        )
        login_params = {
            "country": self._country,
            "language": self._language,
            "svc_code": SVC_CODE,
            "callback_url": V2_WEB_REFERER.rstrip("/"),
        }
        async with session.get(
            url=V2_NSCREEN_AUTH_LOGIN_URL,
            params=login_params,
            headers=login_headers,
            timeout=self._timeout,
            raise_for_status=False,
        ) as resp:
            login_info = await self._get_json_resp(resp)

        redirect_url = (login_info.get("result") or {}).get("redirectUrl")
        if login_info.get("resultCode") != "0000" or not redirect_url:
            raise exc.AuthenticationError("ThinQ Web login URL request failed")

        async with session.get(
            url=redirect_url,
            headers={"User-Agent": V2_WEB_USER_AGENT, "Referer": V2_WEB_REFERER},
            timeout=self._timeout,
            raise_for_status=False,
        ) as resp:
            signin_url = str(resp.url)

        signin_query = parse_qs(urlparse(signin_url).query)
        kc_state = (signin_query.get("kc_state") or [""])[0]
        nonce = (signin_query.get("nonce") or [""])[0]
        if not kc_state or not nonce:
            raise exc.AuthenticationError("ThinQ Web sign-in page request failed")

        hash_pwd = hashlib.sha512()
        hash_pwd.update(password.encode("utf8"))
        signin_data = {
            "userId": await self._web_encrypted_user_id(username),
            "userPw": hash_pwd.hexdigest(),
            "svcCode": SVC_CODE,
            "itgTermsUseFlag": "Y",
            "itgUserType": "",
            "doneYn": "",
            "skipYn": "N",
            "clientId": "",
            "kcState": kc_state,
            "ipadYn": "N",
            "local_country": self._country,
            "local_lang": self._language.split("-")[0],
            "svc_code": SVC_CODE,
        }
        async with session.post(
            url=V2_WEB_SIGNIN_ACT_URL,
            data=urlencode(signin_data),
            headers=self._web_form_headers(signin_url),
            timeout=self._timeout,
            raise_for_status=False,
        ) as resp:
            signin_info = await self._get_json_resp(resp)

        account = signin_info.get("account") or {}
        if not account.get("userNo"):
            raise exc.InvalidCredentialError("ThinQ Web user login failed")

        local_lang = self._language.split("-")[0]
        kc_data = {
            "kc_state": kc_state,
            "nonce": nonce,
            "userNo": account.get("userNo"),
            "userID": account.get("userID"),
            "userIDType": account.get("userIDType"),
            "email": account.get("email") or account.get("userID"),
            "auto_login_yn": "",
            "country": self._country,
            "language": "null",
            "local_country": self._country,
            "local_lang": local_lang,
            "svc_code": SVC_CODE,
        }
        async with session.post(
            url=V2_WEB_KC_CODE_URL,
            data=urlencode(kc_data),
            headers=self._web_form_headers(signin_url),
            timeout=self._timeout,
            raise_for_status=False,
        ) as resp:
            post_signin_url = str(resp.url)
            post_signin_html = await resp.text()

        token_match = re.search(V2_WEB_POST_SIGNIN_TOKEN_RE, post_signin_html)
        if not token_match:
            raise exc.AuthenticationError("ThinQ Web post sign-in token not found")

        extra_headers = self._web_form_headers(post_signin_url)
        await self._web_post_optional(
            V2_WEB_USER_INFO_LEGACY_URL,
            {"local_country": self._country, "local_lang": local_lang, "svc_code": SVC_CODE},
            extra_headers,
        )
        await self._web_post_optional(
            V2_WEB_SEARCH_USER_NO_URL,
            {"userNo": account.get("userNo")},
            extra_headers,
        )
        await self._web_post_optional(
            V2_WEB_SIGNIN_COMPLETE_URL,
            {
                "loginSessionID": account.get("loginSessionID"),
                "uuid": str(uuid.uuid4()),
                "svcCode": SVC_CODE,
                "serviceYn": "Y",
                "deviceId": hashlib.md5(str(uuid.uuid4()).encode()).hexdigest(),
                "autoYn": "N",
                "ipadYn": "N",
                "local_country": self._country,
                "local_lang": local_lang,
                "svc_code": SVC_CODE,
            },
            extra_headers,
        )

        await self._web_follow_login_redirects(
            V2_WEB_DECRYPT_TOKEN_URL,
            {
                "token": token_match.group(1),
                "local_country": self._country,
                "local_lang": local_lang,
                "svc_code": SVC_CODE,
            },
            extra_headers,
        )
        refresh_token = self._web_refresh_token_from_cookie()
        if not refresh_token:
            raise exc.AuthenticationError("ThinQ Web refresh token not found")

        access_token, token_validity = await self.refresh_web_auth(refresh_token)
        user_number = await self.get_web_user_number(access_token)
        if not user_number:
            raise exc.AuthenticationError("ThinQ Web user number not found")
        return {
            "refresh_token": refresh_token,
            "access_token": access_token,
            "token_validity": token_validity,
            "user_number": user_number,
        }

    async def _web_post_optional(
        self, url: str, data: dict, headers: dict
    ) -> None:
        """POST an auxiliary ThinQ Web login request."""
        async with self._get_session().post(
            url=url,
            data=urlencode(data),
            headers=headers,
            timeout=self._timeout,
            raise_for_status=False,
        ) as resp:
            await resp.read()

    async def _web_follow_login_redirects(
        self, url: str, data: dict, headers: dict
    ) -> None:
        """Follow the LG account redirects that create the Web refresh cookie."""
        session = self._get_session()
        referer = headers.get("Referer", V2_WEB_REFERER)
        async with session.post(
            url=url,
            data=urlencode(data),
            headers=headers,
            timeout=self._timeout,
            raise_for_status=False,
            allow_redirects=False,
        ) as resp:
            next_url = resp.headers.get("Location")
            await resp.read()

        for _ in range(8):
            if not next_url:
                return
            next_url = urljoin(referer, next_url)
            async with session.get(
                url=next_url,
                headers={"User-Agent": V2_WEB_USER_AGENT, "Referer": referer},
                timeout=self._timeout,
                raise_for_status=False,
                allow_redirects=False,
            ) as resp:
                referer = str(resp.url)
                next_url = resp.headers.get("Location")
                await resp.read()

    def _web_refresh_token_from_cookie(self) -> str | None:
        """Return the ThinQ Web refresh token stored by the login redirects."""
        cookie_jar = getattr(self._get_session(), "cookie_jar", None)
        if not cookie_jar:
            return None
        for cookie in cookie_jar:
            if cookie.key == "refresh_token":
                return cookie.value
        return None

    async def refresh_web_auth(self, refresh_token: str):
        """Get a ThinQ Web access token using the Web refresh_token cookie."""
        headers = self._thinq2_headers(
            client_id=self._web_client_id(),
            country=self._country,
            language=self._language,
            extra_headers={
                "x-api-key": V2_NSCREEN_API_KEY,
                "x-origin": "webapp",
                "Referer": V2_WEB_REFERER,
                "Cookie": f"refresh_token={refresh_token}",
            },
        )
        async with self._get_session().post(
            url=V2_NSCREEN_AUTH_REFRESH_URL,
            headers=headers,
            timeout=self._timeout,
            raise_for_status=False,
        ) as resp:
            out = await self._get_json_resp(resp)

        if out.get("resultCode") != "0000":
            raise exc.TokenError()

        result = out.get("result") or {}
        access_token = result.get("accessToken")
        if not access_token:
            raise exc.TokenError()
        return access_token, result.get("expiresIn", DEFAULT_TOKEN_VALIDITY)

    async def get_web_user_number(self, access_token: str) -> str | None:
        """Get the ThinQ user number from a ThinQ Web access token."""
        async with self._get_session().get(
            url=V2_WEB_USER_INFO_URL,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {access_token}",
                "Referer": V2_WEB_REFERER,
                "User-Agent": V2_WEB_USER_AGENT,
            },
            timeout=self._timeout,
            raise_for_status=False,
        ) as resp:
            out = await self._get_json_resp(resp)
        return out.get("user_no")


class Gateway:
    """ThinQ authentication gateway."""

    def __init__(self, gw_info: dict, core: CoreAsync) -> None:
        """Initialize the gateway object."""
        self.thinq1_uri = add_end_slash(gw_info["thinq1Uri"])
        self.thinq2_uri = add_end_slash(gw_info["thinq2Uri"])
        self._core = core

    @property
    def core(self) -> CoreAsync:
        """Return the API core."""
        return self._core

    @property
    def country(self) -> str:
        """Return the API core used country."""
        return self._core.country

    @property
    def language(self) -> str:
        """Return the API core used language."""
        return self._core.language

    async def close(self):
        """Close the core aiohttp session."""
        await self._core.close()

    @classmethod
    async def discover(cls, core: CoreAsync) -> Gateway:
        """Return an instance of gateway class."""
        gw_info = await core.gateway_info()
        return cls(gw_info, core)

    def dump(self) -> dict:
        """Dump the gateway objet."""
        return {
            "thinq1Uri": self.thinq1_uri,
            "thinq2Uri": self.thinq2_uri,
            "country": self.country,
            "language": self.language,
        }


class Auth:
    """ThinQ authentication."""

    def __init__(
        self,
        gateway: Gateway,
        refresh_token: str,
        access_token: str | None = None,
        token_validity: str | None = None,
        user_number: str | None = None,
    ) -> None:
        """Initialize ThinQ authentication object."""
        self._gateway: Gateway = gateway
        self.refresh_token = refresh_token
        self.access_token = access_token
        self.token_validity = (
            int(token_validity) if token_validity else DEFAULT_TOKEN_VALIDITY
        )
        self.user_number = user_number
        self._token_created_on = (
            datetime.now(timezone.utc) if access_token else datetime.min
        )

    @property
    def gateway(self) -> Gateway:
        """Return Gateway instance for this Auth."""
        return self._gateway

    @staticmethod
    async def web_auth_info_from_user_login(
        username: str, password: str, core: CoreAsync
    ) -> dict:
        """Return ThinQ Web authentication info using username and password."""
        try:
            result = await core.web_user_login(username, password)
        except exc.AuthenticationError:
            raise
        except Exception as ex:
            raise exc.AuthenticationError("ThinQ Web user login failed") from ex

        if not result:
            raise exc.AuthenticationError("ThinQ Web user login failed")

        return result

    def start_session(self):
        """
        Start an API session for the logged-in user.
        Return the Session object and a list of the user's devices.
        """
        return Session(self)

    async def refresh(self, force_refresh=False) -> Auth:
        """Refresh the authentication token, returning a new Auth object."""

        access_token = self.access_token

        get_new_token: bool = force_refresh or (access_token is None)
        if not get_new_token:
            diff = (datetime.now(timezone.utc) - self._token_created_on).total_seconds()
            if (self.token_validity - diff) <= TOKEN_EXP_LIMIT:
                get_new_token = True

        if get_new_token:
            _LOGGER.debug("Request new access token")
            self.access_token = None
            access_token, token_validity = await self._gateway.core.refresh_web_auth(
                self.refresh_token
            )
        else:
            token_validity = str(self.token_validity)

        if not self.user_number:
            self.user_number = await self._gateway.core.get_web_user_number(
                access_token
            )
            if not self.user_number:
                raise exc.TokenError()

        if not get_new_token:
            return self

        return Auth(
            self._gateway,
            self.refresh_token,
            access_token,
            token_validity,
            self.user_number,
        )

    def refresh_gateway(self, gateway: Gateway) -> None:
        """Refresh the gateway."""
        self._gateway = gateway

    def dump(self) -> dict:
        """Return a dict of dumped Auth class."""
        return {
            "refresh_token": self.refresh_token,
            "access_token": self.access_token,
            "expires_in": self.token_validity,
            "user_number": self.user_number,
        }

    @classmethod
    def load(cls, gateway: Gateway, data: dict) -> Auth:
        """Return an Auth class."""
        return cls(
            gateway,
            data["refresh_token"],
            data.get("access_token"),
            data.get("expires_in"),
            data["user_number"],
        )


class Session:
    """ThinQ authentication session."""

    def __init__(self, auth: Auth, session_id=0) -> None:
        """Initialize session object."""
        self._auth = auth
        self.session_id = session_id
        self._homes: dict | None = None
        self._common_lang_pack_url = None

    @property
    def common_lang_pack_url(self):
        """Return common language pack url."""
        return self._common_lang_pack_url

    async def refresh_auth(self) -> Auth:
        """Refresh associated authentication."""
        self._auth = await self._auth.refresh()
        return self._auth

    async def post(self, path: str, data: dict | None = None) -> dict:
        """
        Make a POST request to the APIv1 server.

        This is like `lgedm_post`, but it pulls the context for the
        request from an active Session.
        """

        url = urljoin(self._auth.gateway.thinq1_uri, path)
        return await self._auth.gateway.core.lgedm2_post(
            url,
            data,
            self._auth.access_token,
            self._auth.user_number,
            is_api_v2=False,
        )

    async def post2(self, path: str, data: dict | None = None) -> dict:
        """
        Make a POST request to the APIv2 server.

        This is like `lgedm_post`, but it pulls the context for the
        request from an active Session.
        """
        url = urljoin(self._auth.gateway.thinq2_uri, path)
        return await self._auth.gateway.core.lgedm2_post(
            url,
            data,
            self._auth.access_token,
            self._auth.user_number,
            is_api_v2=True,
        )

    async def get(self, path: str) -> dict:
        """Make a GET request to the APIv1 server."""

        url = urljoin(self._auth.gateway.thinq1_uri, path)
        return await self._auth.gateway.core.thinq2_get(
            url,
            self._auth.access_token,
            self._auth.user_number,
        )

    async def get2(self, path: str) -> dict:
        """Make a GET request to the APIv2 server."""

        url = urljoin(self._auth.gateway.thinq2_uri, path)
        return await self._auth.gateway.core.thinq2_get(
            url,
            self._auth.access_token,
            self._auth.user_number,
        )

    async def _get_homes(self) -> dict | None:
        """Get a dict of homes associated with the user's account."""
        if self._homes is not None:
            return self._homes

        homes = await self.get2("service/homes")
        if not isinstance(homes, dict):
            _LOGGER.warning("LG API return invalid homes information: '%s'", homes)
            return None

        _LOGGER.debug("Received homes: %s", homes)
        loaded_homes = {}
        homes_list = as_list(homes.get("item", []))
        for home in homes_list:
            if home_id := home.get(_HOME_ID):
                loaded_homes[home_id] = {
                    _HOME_NAME: home.get(_HOME_NAME, "unamed home"),
                    _HOME_CURRENT: home.get(_HOME_CURRENT, "N"),
                }

        if loaded_homes:
            self._homes = loaded_homes
        return loaded_homes

    async def _get_home_devices(self, home_id: str) -> list[dict] | None:
        """
        Get a list of devices associated with the user's home_id.
        Return information about the devices.
        """
        dashboard = await self.get2(f"service/homes/{home_id}")
        if not isinstance(dashboard, dict):
            _LOGGER.warning(
                "LG API return invalid devices information for home_id %s: '%s'",
                home_id,
                dashboard,
            )
            return None

        if self._common_lang_pack_url is None:
            if _COMMON_LANG_URI_ID in dashboard:
                self._common_lang_pack_url = dashboard[_COMMON_LANG_URI_ID]
            else:
                self._common_lang_pack_url = self._auth.gateway.core.lang_pack_url
        return as_list(dashboard.get("devices", []))

    async def get_devices_homes(self) -> list[dict] | None:
        """
        Get a list of devices associated with the user's account.
        Return information about the devices based on homes API call.
        """
        if not (homes := await self._get_homes()):
            _LOGGER.warning("Not possible to determinate a valid home_id")
            return None

        valid_home = False
        devices_list = []
        for home_id in homes:
            if (devices := await self._get_home_devices(home_id)) is None:
                continue
            valid_home = True
            devices_list.extend(devices)

        return devices_list if valid_home else None

    async def get_devices_dashboard(self) -> list[dict] | None:
        """
        Get a list of devices associated with the user's account.
        Return information about the devices based on dashboard API call.
        """
        dashboard = await self.get2("service/application/dashboard")
        if not isinstance(dashboard, dict):
            _LOGGER.warning(
                "LG dashboard API return invalid devices information: '%s'", dashboard
            )
            return None
        if self._common_lang_pack_url is None:
            if _COMMON_LANG_URI_ID in dashboard:
                self._common_lang_pack_url = dashboard[_COMMON_LANG_URI_ID]
            else:
                self._common_lang_pack_url = self._auth.gateway.core.lang_pack_url
        return as_list(dashboard.get("item", []))

    async def get_devices(self) -> list[dict] | None:
        """
        Get a list of devices associated with the user's account.
        Return information about the devices.
        """
        if not _API_USE_HOMES:
            return await self.get_devices_dashboard()
        return await self.get_devices_homes()

    async def monitor_start(self, device_id):
        """
        Begin monitoring a device's status.
        Return a "work ID" that can be used to retrieve the result of
        monitoring.
        """

        res = await self.post(
            "rti/rtiMon",
            {
                "cmd": "Mon",
                "cmdOpt": "Start",
                "deviceId": device_id,
                "workId": gen_uuid(),
            },
        )
        return res["workId"]

    async def monitor_poll(self, device_id, work_id):
        """
        Get the result of a monitoring task.

        `work_id` is a string ID retrieved from `monitor_start`.
        Return a status result, which is a bytestring, or None if the
        monitoring is not yet ready.

        May raise a `MonitorError`, in which case the right course of
        action is probably to restart the monitoring task.
        """

        work_list = [{"deviceId": device_id, "workId": work_id}]
        res = (await self.post("rti/rtiResult", {"workList": work_list}))["workList"]

        # When monitoring first starts, it usually takes a few
        # iterations before data becomes available. In the initial
        # "warmup" phase, `returnCode` is missing from the response.
        if "returnCode" not in res:
            return None

        # Check for errors.
        code = res["returnCode"]
        if code != "0000":
            raise exc.MonitorError(device_id, code)

        # The return data may or may not be present, depending on the
        # monitoring task status.
        if "returnData" in res:
            # The main response payload is base64-encoded binary data in
            # the `returnData` field. This sometimes contains JSON data
            # and sometimes other binary data.
            return base64.b64decode(res["returnData"])

        return None

    async def monitor_stop(self, device_id, work_id):
        """Stop monitoring a device."""

        await self.post(
            "rti/rtiMon",
            {"cmd": "Mon", "cmdOpt": "Stop", "deviceId": device_id, "workId": work_id},
        )

    async def set_device_controls(
        self,
        device_id,
        ctrl_key,
        command=None,
        value=None,
        data=None,
    ):
        """
        Control a device's settings.
        `values` is a key/value map containing the settings to update.
        """
        res = {}
        payload = None
        if isinstance(ctrl_key, dict):
            payload = ctrl_key
        elif command is not None:
            payload = {
                "cmd": ctrl_key,
                "cmdOpt": command,
                "value": value or "",
                "data": data or "",
            }

        if payload:
            payload.update(
                {
                    "deviceId": device_id,
                    "workId": gen_uuid(),
                }
            )
            res = await self.post("rti/rtiControl", payload)

        return res

    async def device_v2_controls(
        self,
        device_id,
        ctrl_key,
        command=None,
        key=None,
        value=None,
        *,
        ctrl_path=None,
    ):
        """Control a device's settings based on api V2."""

        res = {}
        payload = None
        path = ctrl_path or "control-sync"
        cmd_path = f"service/devices/{device_id}/{path}"
        if isinstance(ctrl_key, dict):
            payload = ctrl_key
        elif command is not None:
            payload = {
                "ctrlKey": ctrl_key,
                "command": command,
                "dataKey": key or "",
                "dataValue": "" if value is None else value,
            }

        if payload:
            res = await self.post2(cmd_path, payload)

        return res

    async def get_device_config(self, device_id, key, category="Config"):
        """
        Get a device configuration option.

        The `category` string should probably either be "Config" or
        "Control"; the right choice appears to depend on the key.
        """

        res = await self.post(
            "rti/rtiControl",
            {
                "cmd": category,
                "cmdOpt": "Get",
                "value": key,
                "deviceId": device_id,
                "workId": gen_uuid(),
                "data": "",
            },
        )
        return res["returnData"]

    async def get_device_v2_settings(self, device_id):
        """Get a device's settings based on api V2."""
        return await self.get2(f"service/devices/{device_id}")

    async def delete_permission(self, device_id):
        """Delete permission on V1 device after a control command."""
        await self.post("rti/delControlPermission", {"deviceId": device_id})


class ClientAsync:
    """
    A higher-level API wrapper that provides a session more easily
    and allows serialization of state.
    """

    def __init__(
        self,
        auth: Auth,
        session: Session | None = None,
        country: str = DEFAULT_COUNTRY,
        language: str = DEFAULT_LANGUAGE,
        *,
        enable_emulation: bool = False,
    ) -> None:
        """Initialize the client."""
        # The three steps required to get access to call the API.
        self._auth: Auth = auth
        self._session: Session | None = session
        self._connected = True
        self._last_device_update = datetime.now(timezone.utc)
        self._lock = asyncio.Lock()
        # The last list of devices we got from the server. This is the
        # raw JSON list data describing the devices.
        self._devices = None

        # Cached model info data. This is a mapping from URLs to JSON
        # responses.
        self._model_url_info: dict[str, Any] = {}
        self._common_lang_pack = None
        self._local_lang_pack = None

        # Locale information used to discover a gateway, if necessary.
        self._country = country
        self._language = language

        # enable emulation mode for debug / test
        env_emulation = os.environ.get("thinq2_emulation", "") == "ENABLED"
        self._emulation = env_emulation or enable_emulation

    def _load_emul_devices(self) -> dict | None:
        """This is used only for debug."""
        data_file = os.path.join(
            os.path.dirname(os.path.realpath(__file__)), "deviceV2.txt"
        )
        try:
            with open(data_file, "r", encoding="utf-8") as emu_dev:
                device_v2 = json.load(emu_dev)
        except (FileNotFoundError, json.JSONDecodeError):
            self._emulation = False
            return None
        return device_v2

    async def _load_devices(self, force_update: bool = False):
        """Load dict with available devices."""
        if self._session and (self._devices is None or force_update):
            if (new_devices := await self._session.get_devices()) is None:
                self._devices = None
                return
            if self.emulation:
                # for debug
                if emul_device := await asyncio.to_thread(self._load_emul_devices):
                    new_devices.extend(emul_device)
            self._devices = {
                d[KEY_DEVICE_ID]: d for d in new_devices if KEY_DEVICE_ID in d
            }

    @property
    def api_version(self):
        """Return core API version."""
        return CORE_VERSION

    @property
    def auth(self) -> Auth:
        """Return the Auth object associated to this client."""
        if not self._auth:
            assert False, "unauthenticated"
        return self._auth

    @property
    def client_id(self) -> str | None:
        """Return the associated client_id."""
        if not self._auth:
            return None
        return self._auth.gateway.core.client_id

    @property
    def client_id_created_on(self) -> datetime | None:
        """Return when the associated client_id was created."""
        if not self._auth:
            return None
        return self._auth.gateway.core.client_id_created_on

    @property
    def session(self) -> Session:
        """Return the Session object associated to this client."""
        self._check_connected()
        if not self._session:
            self._session = self.auth.start_session()
        return self._session

    @property
    def has_devices(self) -> bool:
        """Return True if there are devices associated."""
        return bool(self._devices)

    @property
    def devices(self) -> list[DeviceInfo] | None:
        """Return list of DeviceInfo objects describing the user's devices."""
        if self._devices is None:
            return None
        return [DeviceInfo(d) for d in self._devices.values()]

    def get_device(self, device_id: str) -> DeviceInfo | None:
        """Return a DeviceInfo object by device ID or None if the device id does not exist."""
        if not self._devices:
            return None
        if device_id in self._devices:
            return DeviceInfo(self._devices[device_id])
        return None

    @property
    def emulation(self) -> bool:
        """Return if emulation is enabled."""
        return self._emulation

    @property
    def auth_info(self) -> dict:
        """Return current auth info."""
        return {
            "refresh_token": self.auth.refresh_token,
            "access_token": self.auth.access_token,
            "user_number": self.auth.user_number,
        }

    async def close(self):
        """Close the active managed core http session."""
        if not self._connected:
            return
        self._connected = False
        self._session = None
        await self._auth.gateway.close()

    def _check_connected(self):
        """Check that client is in connected status."""
        if not self._connected:
            raise exc.ClientDisconnected()

    async def refresh_devices(self):
        """Refresh the devices' information for this client."""
        async with self._lock:
            call_time = datetime.now(timezone.utc)
            difference = (call_time - self._last_device_update).total_seconds()
            if difference <= MIN_TIME_BETWEEN_UPDATE:
                return
            await self._load_devices(True)
            self._last_device_update = call_time

    async def refresh(self, refresh_gateway=False) -> None:
        """Refresh client connection."""
        self._check_connected()
        if refresh_gateway:
            gateway = await Gateway.discover(self.auth.gateway.core)
            self.auth.refresh_gateway(gateway)
        self._auth = await self.auth.refresh(True)
        self._session = self.auth.start_session()
        await self._load_devices()

    async def refresh_auth(self) -> None:
        """Refresh auth token if requested."""
        if self._session:
            self._auth = await self._session.refresh_auth()
        else:
            await self.refresh()

    @classmethod
    async def from_token(
        cls,
        refresh_token: str,
        *,
        country: str = DEFAULT_COUNTRY,
        language: str = DEFAULT_LANGUAGE,
        aiohttp_session: aiohttp.ClientSession | None = None,
        client_id: str | None = None,
        client_id_created_on: datetime | None = None,
        update_clientid_callback: Callable[[str, datetime], None] | None = None,
        enable_emulation: bool = False,
    ) -> ClientAsync:
        """
        Construct a client using just a refresh token.

        This allows simpler state storage (e.g., for human-written
        configuration) but it is a little less efficient because we need
        to reload the gateway servers and restart the session.
        """

        core = CoreAsync(
            country,
            language,
            session=aiohttp_session,
            client_id=client_id,
            client_id_created_on=client_id_created_on,
            update_clientid_callback=update_clientid_callback,
        )
        try:
            gateway = await Gateway.discover(core)
            auth = Auth(gateway, refresh_token)
            client = cls(
                auth=auth,
                country=country,
                language=language,
                enable_emulation=enable_emulation,
            )
            await client.refresh()
        except Exception:  # pylint: disable=broad-except
            await core.close()
            raise

        return client

    @staticmethod
    async def auth_info_from_user_login(
        username: str,
        password: str,
        country: str = DEFAULT_COUNTRY,
        language: str = DEFAULT_LANGUAGE,
        *,
        aiohttp_session: aiohttp.ClientSession | None = None,
    ) -> dict:
        """Return ThinQ Web authentication info from username and password."""
        core = CoreAsync(
            country,
            language,
            session=aiohttp_session,
        )
        try:
            result = await Auth.web_auth_info_from_user_login(username, password, core)
        finally:
            await core.close()

        return result

    async def _load_json_info(self, info_url: str):
        """Load JSON data from specific url."""
        self._check_connected()
        if not info_url:
            return {}

        content = await self._auth.gateway.core.http_get_bytes(info_url)

        def _load_json_content():
            """Decode and load as json the received content."""
            try:
                # we use charset_normalizer to detect correct encoding and convert to unicode string
                str_content = str(from_bytes(content).best(), errors="replace")
            except (LookupError, TypeError):
                # A LookupError is raised if the encoding was not found which could
                # indicate a misspelling or similar mistake.
                #
                # A TypeError can be raised if encoding is None
                #
                # So we try blindly encoding.
                str_content = str(content, errors="replace")

            enc_resp = str_content.encode()
            try:
                return json.loads(enc_resp)
            except json.JSONDecodeError as ex:
                _LOGGER.warning(
                    "Failed to load json info file: %s - error: %s", info_url, ex
                )
                return None

        return await asyncio.to_thread(_load_json_content)

    async def common_lang_pack(self):
        """Load JSON common lang pack from specific url."""
        if self._devices is None:
            return {}
        if self._common_lang_pack is None and self._session:
            self._common_lang_pack = (
                await self._load_json_info(self._session.common_lang_pack_url)
            ).get("pack", {})
        return self._common_lang_pack

    async def local_lang_pack(self) -> dict[str, str]:
        """Load JSON local lang pack from local."""
        if self._local_lang_pack is not None:
            return self._local_lang_pack

        def _load_local_lang_pack() -> dict[str, dict]:
            """Load content of local lang pack."""
            data_file = os.path.join(
                os.path.dirname(os.path.realpath(__file__)), _LOCAL_LANG_FILE
            )
            try:
                with open(data_file, "r", encoding="utf-8") as lang_file:
                    return json.load(lang_file)
            except (FileNotFoundError, json.JSONDecodeError):
                return {}

        lang_pack = await asyncio.to_thread(_load_local_lang_pack)

        if self._language in lang_pack:
            result = lang_pack[self._language]
        else:
            result = lang_pack.get(DEFAULT_LANGUAGE, {})

        self._local_lang_pack = result
        return result

    async def model_url_info(self, url, device=None):
        """
        For a DeviceInfo object, get a ModelInfo object describing
        the model's capabilities.
        """
        if not url:
            return {}
        if url not in self._model_url_info:
            if device:
                _LOGGER.debug(
                    "Loading model info for %s. Model: %s, Url: %s",
                    device.name,
                    device.model_name,
                    url,
                )
            if not (model_url_info := await self._load_json_info(url)):
                return None
            self._model_url_info[url] = model_url_info
        return self._model_url_info[url]

    def dump(self) -> dict[str, Any]:
        """Serialize the client state."""

        out = {
            "model_url_info": self._model_url_info,
        }

        if self._auth:
            out["auth"] = self._auth.dump()
            out["gateway"] = self._auth.gateway.dump()

        if self._session:
            out["session"] = self._session.session_id

        out["country"] = self._country
        out["language"] = self._language

        return out

    @classmethod
    def load(cls, state: dict[str, Any]) -> ClientAsync | None:
        """Load a client from serialized state."""

        auth = None
        gateway = None
        if "gateway" in state:
            data = state["gateway"]
            gateway = Gateway(
                data,
                CoreAsync(
                    data.get("country", DEFAULT_COUNTRY),
                    data.get("language", DEFAULT_LANGUAGE),
                ),
            )

        if "auth" in state and gateway:
            data = state["auth"]
            auth = Auth.load(gateway, data)

        if not auth:
            return None

        client = cls(auth)

        if "session" in state:
            client._session = Session(client.auth, state["session"])

        if "model_url_info" in state:
            client._model_url_info = state["model_url_info"]

        if "country" in state:
            client._country = state["country"]

        if "language" in state:
            client._language = state["language"]

        return client
