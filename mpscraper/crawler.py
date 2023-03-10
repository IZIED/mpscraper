from __future__ import annotations

import enum
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Generic, Literal, NamedTuple, TypeVar

from loguru import logger

from mpscraper.const import DUMP_DIR
from mpscraper.models import BidStatus

F = TypeVar("F", str, bytes)


class VirtualFile(NamedTuple, Generic[F]):
    filename: str
    content: F


AgilResultsCrawlContent = VirtualFile[str]


class AgilCrawlContents(NamedTuple):
    main: str  # html
    modals: list[str]  # json
    modal_selected: str | None  # json
    provider_listing: VirtualFile[str] | None  # xls/html
    bo_pdf: VirtualFile[bytes] | None  # pdf
    bo_screen: str | None  # html


class Credentials(NamedTuple):
    username: str
    password: str


class MerPubSection(enum.Enum):
    AGIL = 1


class Crawler:
    """Base para un Crawler con Playwright."""

    def __init__(self):
        from playwright.sync_api import sync_playwright

        logger.debug("Iniciando Playwright con Chromium")
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch()
        self.context = self.browser.new_context()
        self.page = self.context.new_page()

    def __del__(self):
        self.context.close()
        self.browser.close()
        self.playwright.stop()

    def save_dump(self, dir: str | os.PathLike = DUMP_DIR):
        dir = Path(dir)
        now = int(datetime.now().timestamp())
        now = str(now)
        scr_path = dir / (now + ".png")
        html_path = dir / (now + ".html")
        logger.debug(f"Guardando volcados como: {scr_path!r} y {html_path!r}")
        scr_path.write_bytes(self.page.screenshot(full_page=True))
        html_path.write_text(self.page.content(), "utf-8")


class MerPubCrawler(Crawler):
    MAIN_FRAME_NAME = "fraDetalle"
    HOME_URL = "https://www.mercadopublico.cl/Home"
    PORTAL_URL = "https://www.mercadopublico.cl/Portal/Modules/Menu/Menu.aspx"
    BUSQUEDA_AGIL_URL_PREFIX = (
        "https://www.mercadopublico.cl/CompraAgil/Modules/Cotizacion/"
    )
    BUSQUEDA_AGIL_URL = BUSQUEDA_AGIL_URL_PREFIX + "BuscarCotizacion.aspx"
    VER_DETALLE_RE = re.compile("Ver detalle|Participa")
    VER_DETALLE_ONCLICK_RE = re.compile(
        r"^window\.location='(?P<url>(?:[^'\\]|\\.)*)';.*$"
    )
    AJAX_MODAL_INFO_URL = "https://www.mercadopublico.cl/CompraAgil/Modules/Cotizacion/SeleccionProveedor.aspx/ObtenerDatosCotizacion"

    def __init__(self, credentials: Credentials):
        super().__init__()
        self.credentials = credentials

    def login_merpub(self):
        """Intenta iniciar sesi??n en Mercado P??blico con las credenciales
        del crawler.

        Reintenta hasta que pueda, o falla en caso de que la cuenta
        aparezca como bloqueada."""
        from playwright._impl._api_types import TimeoutError

        logger.info("Iniciando sesi??n en Mercado P??blico")
        p = self.page

        def main_process():
            p.goto(self.HOME_URL)

            p.get_by_role("button", name="Iniciar Sesi??n").click()
            p.get_by_role("link", name="Clave??nica").click()

            # si se ha iniciado sesi??n previamente, puede que se
            # salte la parte de inicio de sesi??n con Clave ??nica
            if p.url.startswith("https://accounts.claveunica.gob.cl/"):
                logger.debug("Iniciando sesi??n con Clave ??nica")
                p.wait_for_load_state()
                p.locator("#uname").type(self.credentials.username)  # Ingresa tu RUN
                p.locator("#pword").type(self.credentials.password)  # Ingresa tu Clave
                p.get_by_role("button", name="Continuar").click()
            else:
                logger.debug("Sesi??n previamente iniciada; saltando Clave ??nica")

        while True:
            main_process()
            p.wait_for_load_state()
            if p.query_selector(".swal2-container"):
                raise Exception("La cuenta aparece como bloqueada")
            try:
                if p.wait_for_selector(".rdbOrganismo", timeout=2500):
                    break
            except TimeoutError:
                logger.warning(
                    "Lista de organismos no mostrada al iniciar sesi??n; reintentando"
                )
                pass

        # check for '#kc-error-message'

        p.click(".rdbOrganismo")  # primer organismo en lista
        p.get_by_role("link", name="Ingresar").click()
        logger.success("Sesi??n iniciada en Mercado P??blico")

    @property
    def f(self):
        """El frame donde se navega dentro del portal."""
        f = self.page.frame(self.MAIN_FRAME_NAME)
        if not f:
            raise Exception("No se encontr?? el frame principal")
        return f

    @property
    def fl(self):
        """Un FrameLocator del frame donde se navega dentro del portal."""
        return self.page.frame_locator("#" + self.MAIN_FRAME_NAME)

    def inject_instructions_modal_dismisser(self):
        """Inyecta un script en la p??gina del portal que trata de quitar
        el modal de explicaci??n cada 500 ms en el frame correspondiente."""

        logger.debug("Injectando JS para ignorar modal de explicaci??n en b??squeda ??gil")
        self.page.wait_for_load_state()
        self.f.wait_for_load_state()
        self.f.evaluate(
            "setInterval(function () {"
            "    document.getElementById('fraDetalle')"
            "        .contentWindow.$('#modalStepper').modal('hide');"
            "}, 500);"
        )
        # self.f.evaluate("$('#modalStepper').modal('hide');")

    def visit_merpub_section(self, section: MerPubSection):
        """Visita una secci??n de mercado p??blico.

        Requiere tener la sesi??n iniciada, por lo que intenta iniciar
        sesi??n si no se encuentra con la sesi??n iniciada."""
        p = self.page
        if p.url != self.PORTAL_URL:
            p.goto(self.PORTAL_URL)
            # p.wait_for_load_state()
            if p.url == self.HOME_URL:
                self.login_merpub()
                self.page.wait_for_load_state()
            self.inject_instructions_modal_dismisser()

        logger.debug(f"Visitando portal de {section!r}")
        match section:
            case MerPubSection.AGIL:
                if self.f.url != self.BUSQUEDA_AGIL_URL:
                    self.fl.get_by_role("link", name="COMPRA ??GIL").click()
                    p.wait_for_load_state()
        p.wait_for_load_state()

    def crawl_results_from_agil_params(
        self,
        *,
        date_from: date,
        date_until: date,
        status: Literal["*"] | BidStatus = "*",
    ) -> AgilResultsCrawlContent | None:
        """Realiza una b??squeda en licitaciones ??giles y entrega la lista de resultados.

        Si no se encuentra ning??n resultado, no retorna nada."""
        self.visit_merpub_section(MerPubSection.AGIL)

        logger.debug(
            f"Configurando b??squeda ??gil: categor??a={status!r}, desde={date_from!r}, hasta={date_until!r}"
        )
        self.fl.get_by_text("Solamente cotizaciones de mis rubros").click()

        val = 0
        match status:
            case "*":
                val = 0
            case BidStatus.PUBLISHED:
                val = 2
            case BidStatus.CLOSED:
                val = 3
            case BidStatus.BO_EMITTED:
                val = 4
            case BidStatus.CANCELLED:
                val = 5
        ddl_lo = self.fl.locator("#ddlState")  # "Estado"
        ddl_lo.select_option(str(val))
        ddl_lo.focus()
        self.page.keyboard.down("Tab")

        df_lo = self.fl.locator("#fdesde")
        df_lo.type(date_from.strftime("%d%m%Y"), delay=50)  # "Fecha Desde:"
        self.page.keyboard.down("Tab")

        dt_lo = self.fl.locator("#fhasta")
        dt_lo.type(date_until.strftime("%d%m%Y"), delay=50)  # "Fecha Hasta:"
        self.page.keyboard.down("Tab")

        self.fl.locator("#btnSearchParameter").click()  # "Buscar"

        self.save_dump()

        lo = self.fl.locator("#lnkDownloadExcel")  # "Descargar resultados en excel"
        if lo.count():
            logger.debug("Descargando lista de resultados")
            # self.ignore_instructions_modal()
            with self.page.expect_download() as download_info:
                self.page.wait_for_timeout(250)
                self.f.evaluate("__doPostBack('lnkDownloadExcel','');")
                self.page.wait_for_timeout(250)

            path = download_info.value.path()
            if not path:
                raise Exception("La descarga no se termin??")
            file = path.read_text()

            return VirtualFile(download_info.value.suggested_filename, file)
        else:  # No se encontraron resultados
            logger.warning("No se encontr?? ning??n resultado")
            return None

    def crawl_from_agil_idn(self, idn: str) -> AgilCrawlContents | None:
        """Extrae los contenidos de una licitaci??n buscando a base de su n??mero."""
        logger.debug(f"Descargando datos de licitaci??n ??gil: idn={idn}")
        self.visit_merpub_section(MerPubSection.AGIL)

        self.fl.locator("#txtIDQuote").fill(idn)  # "Busca Por ID"

        self.fl.get_by_role("button", name="Buscar ID").click()
        self.f.wait_for_load_state()

        logger.debug("Tratando de entrar a p??gina de contenido de licitaci??n")
        # "Ver detalle" en resultados
        lo = self.fl.get_by_role("button", name=self.VER_DETALLE_RE)
        match = self.VER_DETALLE_ONCLICK_RE.match(lo.get_attribute("onclick") or "")
        if not match:
            raise Exception()
        self.f.goto(self.BUSQUEDA_AGIL_URL_PREFIX + match["url"])

        if self.f.url == self.BUSQUEDA_AGIL_URL:
            pass

        logger.debug(f"En url: {self.f.url!r}")

        html = self.f.content()

        # "Descargar listado en excel"
        lo = self.fl.locator("#lnkDownloadExcel")
        if lo.count():
            logger.debug("Listado de proveedores encontrado; descargando lista")
            with self.page.expect_download() as download_info:
                self.page.wait_for_timeout(500)
                self.f.evaluate("__doPostBack('lnkDownloadExcel','');")
                self.page.wait_for_timeout(500)
            path = download_info.value.path()
            if not path:
                raise Exception("La descarga no se termin??")
            file = path.read_text()
            provider_listing = VirtualFile(download_info.value.suggested_filename, file)
        else:
            logger.debug("No se detect?? listado de proveedores")
            provider_listing = None

        # "Ver orden de compra"
        lo = self.fl.locator("#lnkOrdenCompra:not(.disabled)")
        if lo.count():
            logger.debug("Orden de compra detectada; descargando")
            with self.page.expect_popup() as pu:
                lo.click()
            pu = pu.value
            bo_screen = pu.content()

            with pu.expect_download() as download_info:
                with pu.expect_popup() as pdf_pu:
                    logger.debug("Descargando PDF de la orden de compra")
                    pu.locator("#imgPDF").click()  # "PDF"
                pdf_pu = pdf_pu.value
            path = download_info.value.path()
            if not path:
                raise Exception("La descarga no se termin??")
            bo_pdf = VirtualFile(
                download_info.value.suggested_filename, path.read_bytes()
            )
            pdf_pu.close()
            pu.close()
        else:
            logger.debug("No fue detectada una orden de compra")
            bo_screen = None
            bo_pdf = None

        modal_contents = []
        selected_modal_content = None
        # Para hacer requests AJAX hay un input oculto que contiene una id que necesitamos
        hidden_id = self.fl.locator("#hdnIdSolicitud")
        if hidden_id.count():
            hidden_id = int(hidden_id.get_attribute("value"))  # type: ignore
            lo = self.fl.locator("#GvProvider")
            if lo.count():
                logger.debug("Descargando modales de proveedores")
                modal_links = lo.get_by_role("button", name="Ver detalle")
                if modal_links.count():
                    for link in modal_links.all():
                        # El enlace para ver el modal contiene una id que necesitamos
                        id_modal = link.get_attribute("data-qs2")
                        if not id_modal:
                            continue
                        id_modal = int(id_modal)
                        response = self.page.request.fetch(
                            self.AJAX_MODAL_INFO_URL,
                            headers={
                                "accept": "application/json, text/javascript, */*; q=0.01",
                                "content-type": "application/json; charset=UTF-8",
                                "x-requested-with": "XMLHttpRequest",
                            },
                            data={"idSolicitud": hidden_id, "idCotizacion": id_modal},
                            method="POST",
                        )
                        if response.ok:
                            modal_contents.append(response.text())

            lo = self.fl.locator("#gvSeleccionado")
            if lo.count():
                logger.debug("Hay un proveedor seleccionado; descargando modal")
                link = lo.get_by_role("button", name="Ver detalle")
                # El enlace para ver el modal contiene una id que necesitamos
                id_modal = link.get_attribute("data-qs2")
                id_modal = int(id_modal)  # type: ignore
                response = self.page.request.fetch(
                    self.AJAX_MODAL_INFO_URL,
                    headers={
                        "accept": "application/json, text/javascript, */*; q=0.01",
                        "content-type": "application/json; charset=UTF-8",
                        "x-requested-with": "XMLHttpRequest",
                    },
                    data={"idSolicitud": hidden_id, "idCotizacion": id_modal},
                    method="POST",
                )
                if response.ok:
                    selected_modal_content = response.text()

        logger.success(f"Licitaci??n {idn!r} con sus datos descargados")

        return AgilCrawlContents(
            html,
            modal_contents,
            selected_modal_content,
            provider_listing,
            bo_pdf,
            bo_screen,
        )
