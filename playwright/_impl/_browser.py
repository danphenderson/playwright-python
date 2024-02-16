# Copyright (c) Microsoft Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Dict, List, Optional, Pattern, Sequence, Union, cast

from playwright._impl._api_structures import (
    Geolocation,
    HttpCredentials,
    ProxySettings,
    StorageState,
    ViewportSize,
)
from playwright._impl._artifact import Artifact
from playwright._impl._browser_context import BrowserContext
from playwright._impl._cdp_session import CDPSession
from playwright._impl._connection import ChannelOwner, from_channel
from playwright._impl._errors import is_target_closed_error
from playwright._impl._helper import (
    ColorScheme,
    ForcedColors,
    HarContentPolicy,
    HarMode,
    ReducedMotion,
    ServiceWorkersPolicy,
    async_readfile,
    locals_to_params,
    make_dirs_for_file,
    prepare_record_har_options,
)
from playwright._impl._network import serialize_headers
from playwright._impl._page import Page

if TYPE_CHECKING:  # pragma: no cover
    from playwright._impl._browser_type import BrowserType


class Browser(ChannelOwner):
    Events = SimpleNamespace(
        Disconnected="disconnected",
    )

    def __init__(
        self, parent: "BrowserType", type: str, guid: str, initializer: Dict
    ) -> None:
        super().__init__(parent, type, guid, initializer)
        self._browser_type = parent
        self._is_connected = True
        self._should_close_connection_on_close = False
        self._cr_tracing_path: Optional[str] = None

        self._contexts: List[BrowserContext] = []
        self._channel.on("close", lambda _: self._on_close())
        self._close_reason: Optional[str] = None

    def __repr__(self) -> str:
        return f"<Browser type={self._browser_type} version={self.version}>"

    def _on_close(self) -> None:
        self._is_connected = False
        self.emit(Browser.Events.Disconnected, self)

    @property
    def contexts(self) -> List[BrowserContext]:
        return self._contexts.copy()

    @property
    def browser_type(self) -> "BrowserType":
        return self._browser_type

    def is_connected(self) -> bool:
        return self._is_connected

    async def new_context(
        self,
        viewport: Optional[ViewportSize] = None,
        screen: Optional[ViewportSize] = None,
        noViewport: Optional[bool] = None,
        ignoreHTTPSErrors: Optional[bool] = None,
        javaScriptEnabled: Optional[bool] = None,
        bypassCSP: Optional[bool] = None,
        userAgent: Optional[str] = None,
        locale: Optional[str] = None,
        timezoneId: Optional[str] = None,
        geolocation: Optional[Geolocation] = None,
        permissions: Optional[Sequence[str]] = None,
        extraHTTPHeaders: Optional[Dict[str, str]] = None,
        offline: Optional[bool] = None,
        httpCredentials: Optional[HttpCredentials] = None,
        deviceScaleFactor: Optional[float] = None,
        isMobile: Optional[bool] = None,
        hasTouch: Optional[bool] = None,
        colorScheme: Optional[ColorScheme] = None,
        reducedMotion: Optional[ReducedMotion] = None,
        forcedColors: Optional[ForcedColors] = None,
        acceptDownloads: Optional[bool] = None,
        defaultBrowserType: Optional[str] = None,
        proxy: Optional[ProxySettings] = None,
        recordHarPath: Optional[Union[Path, str]] = None,
        recordHarOmitContent: Optional[bool] = None,
        recordVideoDir: Optional[Union[Path, str]] = None,
        recordVideoSize: Optional[ViewportSize] = None,
        storageState: Optional[Union[StorageState, str, Path]] = None,
        baseURL: Optional[str] = None,
        strictSelectors: Optional[bool] = None,
        serviceWorkers: Optional[ServiceWorkersPolicy] = None,
        recordHarUrlFilter: Optional[Union[Pattern[str], str]] = None,
        recordHarMode: Optional[HarMode] = None,
        recordHarContent: Optional[HarContentPolicy] = None,
    ) -> BrowserContext:
        params = locals_to_params(locals())
        await prepare_browser_context_params(params)

        channel = await self._channel.send("newContext", params)
        context = cast(BrowserContext, from_channel(channel))
        self._browser_type._did_create_context(context, params, {})
        return context

    async def new_page(
        self,
        viewport: Optional[ViewportSize] = None,
        screen: Optional[ViewportSize] = None,
        noViewport: Optional[bool] = None,
        ignoreHTTPSErrors: Optional[bool] = None,
        javaScriptEnabled: Optional[bool] = None,
        bypassCSP: Optional[bool] = None,
        userAgent: Optional[str] = None,
        locale: Optional[str] = None,
        timezoneId: Optional[str] = None,
        geolocation: Optional[Geolocation] = None,
        permissions: Optional[Sequence[str]] = None,
        extraHTTPHeaders: Optional[Dict[str, str]] = None,
        offline: Optional[bool] = None,
        httpCredentials: Optional[HttpCredentials] = None,
        deviceScaleFactor: Optional[float] = None,
        isMobile: Optional[bool] = None,
        hasTouch: Optional[bool] = None,
        colorScheme: Optional[ColorScheme] = None,
        forcedColors: Optional[ForcedColors] = None,
        reducedMotion: Optional[ReducedMotion] = None,
        acceptDownloads: Optional[bool] = None,
        defaultBrowserType: Optional[str] = None,
        proxy: Optional[ProxySettings] = None,
        recordHarPath: Optional[Union[Path, str]] = None,
        recordHarOmitContent: Optional[bool] = None,
        recordVideoDir: Optional[Union[Path, str]] = None,
        recordVideoSize: Optional[ViewportSize] = None,
        storageState: Optional[Union[StorageState, str, Path]] = None,
        baseURL: Optional[str] = None,
        strictSelectors: Optional[bool] = None,
        serviceWorkers: Optional[ServiceWorkersPolicy] = None,
        recordHarUrlFilter: Optional[Union[Pattern[str], str]] = None,
        recordHarMode: Optional[HarMode] = None,
        recordHarContent: Optional[HarContentPolicy] = None,
    ) -> Page:
        params = locals_to_params(locals())

        async def inner() -> Page:
            context = await self.new_context(**params)
            page = await context.new_page()
            page._owned_context = context
            context._owner_page = page
            return page

        return await self._connection.wrap_api_call(inner)

    async def close(self, reason: Optional[str] = None) -> None:
        self._close_reason = reason
        try:
            if self._should_close_connection_on_close:
                await self._connection.stop_async()
            else:
                await self._channel.send("close", {"reason": reason})
        except Exception as e:
            if not is_target_closed_error(e):
                raise e

    @property
    def version(self) -> str:
        return self._initializer["version"]

    async def new_browser_cdp_session(self) -> CDPSession:
        return from_channel(await self._channel.send("newBrowserCDPSession"))

    async def start_tracing(
        self,
        page: Optional[Page] = None,
        path: Optional[Union[str, Path]] = None,
        screenshots: Optional[bool] = None,
        categories: Optional[Sequence[str]] = None,
    ) -> None:
        params = locals_to_params(locals())
        if page:
            params["page"] = page._channel
        if path:
            self._cr_tracing_path = str(path)
            params["path"] = str(path)
        await self._channel.send("startTracing", params)

    async def stop_tracing(self) -> bytes:
        artifact = cast(Artifact, from_channel(await self._channel.send("stopTracing")))
        buffer = await artifact.read_info_buffer()
        await artifact.delete()
        if self._cr_tracing_path:
            make_dirs_for_file(self._cr_tracing_path)
            with open(self._cr_tracing_path, "wb") as f:
                f.write(buffer)
            self._cr_tracing_path = None
        return buffer


async def prepare_browser_context_params(params: Dict) -> None:
    if params.get("noViewport"):
        del params["noViewport"]
        params["noDefaultViewport"] = True
    if "defaultBrowserType" in params:
        del params["defaultBrowserType"]
    if "extraHTTPHeaders" in params:
        params["extraHTTPHeaders"] = serialize_headers(params["extraHTTPHeaders"])
    if "recordHarPath" in params:
        params["recordHar"] = prepare_record_har_options(params)
        del params["recordHarPath"]
    if "recordVideoDir" in params:
        params["recordVideo"] = {"dir": Path(params["recordVideoDir"]).absolute()}
        if "recordVideoSize" in params:
            params["recordVideo"]["size"] = params["recordVideoSize"]
            del params["recordVideoSize"]
        del params["recordVideoDir"]
    if "storageState" in params:
        storageState = params["storageState"]
        if not isinstance(storageState, dict):
            params["storageState"] = json.loads(
                (await async_readfile(storageState)).decode()
            )
    if params.get("colorScheme", None) == "null":
        params["colorScheme"] = "no-override"
    if params.get("reducedMotion", None) == "null":
        params["reducedMotion"] = "no-override"
    if params.get("forcedColors", None) == "null":
        params["forcedColors"] = "no-override"
    if "acceptDownloads" in params:
        params["acceptDownloads"] = "accept" if params["acceptDownloads"] else "deny"
