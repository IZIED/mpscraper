from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from pathlib import Path
import sys
from typing import Mapping, Set

from loguru import logger

from mpscraper.const import DATABASE_CONNECTION, DUMP_DIR, WORK_DIR
from mpscraper.crawler import AgilCrawlContents, Credentials, MerPubCrawler, VirtualFile
from mpscraper.database import merge_agil_models_into_db
from mpscraper.models import BidStatus
from mpscraper.parser import parse_agil_into_db_model, parse_agil_search_results_html
from mpscraper.validators import validate_rut


def prepare_database(engine, session):
    from mpscraper.models import Base, init_database

    logger.info("Preparando la base de datos")
    logger.debug("Creando tablas, si no están creadas")
    Base.metadata.create_all(engine)

    logger.debug("Populando datos estáticos")
    init_database(session)


def get_ignores(session):
    import sqlalchemy

    import mpscraper.models

    in_db: set[str] = {
        row[0].idn for row in session.execute(sqlalchemy.select(mpscraper.models.Bid))
    }
    in_cache = {d.name for d in WORK_DIR.glob("*/")}
    return in_db.union(in_cache)


def scrape(args, ignores: Set[str]):
    if not args.login or not args.password:
        ap.error("--login y --password son necesarios si se van a extraer datos")
    username = args.login
    username = validate_rut(username, lenient=True)
    if username is False:
        ap.error("--login tiene que ser un RUT válido")
    username = username.replace("-", "")
    password = args.password
    if not args.category:
        ap.error(
            "--category, --from y --until son necesarios si se van a extraer datos"
        )
    category = "*" if args.category == "*" else BidStatus[args.category]
    if args.days_before:
        until = date.today()
        from_ = until - timedelta(args.days_before)
    elif args.from_ and not args.until:
        until = args.until
        from_ = args.from_
    else:
        ap.error(
            "--from y --until o --days-before son necesarios si se van a extraer datos"
        )
    limit = args.limit
    logger.info("Extrayendo datos de Mercado Público")
    result_list = None
    ignore = ignores if args.only_missing else set()
    try:
        crawler = MerPubCrawler(credentials=Credentials(username, password))
    except Exception as err:
        logger.error(f"Hubo un error al crear el crawler: {err!r}")
        return None
    try:
        file = crawler.crawl_results_from_agil_params(
            date_from=from_,
            date_until=until,
            status=category,
        )
        if not file:
            raise Exception("No hubieron resultados")
        result_list = parse_agil_search_results_html(file.content)
    except Exception as err:
        logger.error(f"Hubo un error al extraer la lista de resultados: {err!r}")
        crawler.save_dump(DUMP_DIR)
        return None
    limit = min(limit, len(result_list)) or len(result_list)
    logger.info(f"Se esperan extraer {limit} licitaciones, si no se ignora ninguno")
    ripped = {}
    count = 0
    for idx, idn in enumerate(result_list.keys()):
        if idn in ignore:
            logger.info(
                f"Ignorando licitación {idn!r}, ya se encuentra localmente; ignorando"
            )
            limit -= 1
            continue
        try:
            result = crawler.crawl_from_agil_idn(idn)
            yield idn, result
            ripped[idn] = result
            count += 1
            if count >= limit:
                break
        except Exception as err:
            logger.exception(err)
            logger.error(f"Hubo un error al extraer la licitación {idn!r}, ignorando")
            crawler.save_dump(DUMP_DIR)
    if len(ripped) < limit:
        logger.warning(f"No se extrajeron todas las licitaciones esperadas")
    logger.success(f"{len(ripped)} licitaciones extraídas")


def save_files(ripped: Mapping[str, AgilCrawlContents]):
    import shutil

    tmpdir = WORK_DIR
    logger.info("Guardando archivos extraídos de forma local")
    for idn, result in ripped.items():
        savedir: Path = tmpdir / idn
        if savedir.exists():
            shutil.rmtree(savedir)
        savedir.mkdir(exist_ok=True)
        (savedir / "bid.html").write_text(result.main, encoding="utf-8")
        if result.bo_pdf:
            (savedir / result.bo_pdf.filename).write_bytes(result.bo_pdf.content)
        if result.bo_screen:
            (savedir / "bo.html").write_text(result.bo_screen, encoding="utf-8")
        if result.provider_listing:
            (savedir / result.provider_listing.filename).write_text(
                result.provider_listing.content, encoding="utf-8"
            )
        if result.modals:
            for idx, modal in enumerate(result.modals):
                (savedir / f"modal_{idx}.json").write_text(
                    modal or "", encoding="utf-8"
                )
        if result.modal_selected:
            (savedir / f"selected_modal.json").write_text(
                result.modal_selected, encoding="utf-8"
            )


def load_files() -> Mapping[str, AgilCrawlContents]:
    tmpdir = Path("./__workdir__")
    tmpdir.mkdir(exist_ok=True)
    ripped: Mapping[str, AgilCrawlContents] = {}
    for folder in tmpdir.glob("*/"):
        modals = [fn.read_text("utf-8") for fn in folder.glob("modal_*.json")]
        provider_listing = next(folder.glob("ProveedoresCotizacionCAgil_*.xls"))
        provider_listing = (
            VirtualFile(provider_listing.name, provider_listing.read_text("utf-8"))
            if provider_listing
            else None
        )
        modal_selected = next(folder.glob("selected_modal.json"))
        modal_selected = modal_selected.read_text("utf-8") if modal_selected else None
        main = (folder / "bid.html").read_text("utf-8")
        ripped[folder.name] = AgilCrawlContents(
            main, modals, modal_selected, provider_listing, None, None
        )
    return ripped


def parse(session, agils: Mapping[str, AgilCrawlContents]):
    logger.info(f"Añadiendo modelos de {len(agils)} entradas de licitaciones ágiles")
    count = 0
    for idn, agil in agils.items():
        try:
            models = parse_agil_into_db_model(agil)
        except Exception as err:
            logger.exception(err)
            logger.error(
                f"Hubo un error al parsear los archivos de licitación {idn!r}, ignorando"
            )
            continue
        try:
            merge_agil_models_into_db(session, models)
            session.commit()
            count += 1
        except Exception as err:
            logger.exception(err)
            logger.error(
                f"Hubo un error al ingresar los datos de licitación {idn!r} parseados a la base de datos"
            )
            session.rollback()
    if count:
        logger.success("Base de datos actualizada con nuevos datos")


def date_arg(value: str):
    try:
        return datetime.strptime(value, r"%Y-%m-%d") if value else None
    except ValueError:
        return argparse.ArgumentTypeError(
            "{value!r} no es un formato de fecha válido (AAAA-MM-DD)"
        )


ap = argparse.ArgumentParser("mpscraper")
ap.add_argument(
    "--scrape",
    "-s",
    action=argparse.BooleanOptionalAction,
    help="extraer datos de Mercado Público",
    default=True,
)
ap.add_argument(
    "--login", "-l", type=str, help="RUT a usar para acceder a Mercado Público"
)
ap.add_argument(
    "--password",
    "-p",
    type=str,
    help="contraseña a usar para acceder a Mercado Público",
)
ap.add_argument("--database", "-d", type=str, help="string de conexión a la base de datos a usar")
ap.add_argument(
    "--from",
    "-f",
    dest="from_",
    type=date_arg,
    help="en búsqueda de licitación ágil: fecha de inicio",
)
ap.add_argument(
    "--until", "-u", type=date_arg, help="en búsqueda de licitación ágil: fecha límite"
)
ap.add_argument(
    "--days-before",
    type=int,
    help="en búsqueda de licitación ágil: número de días antes de la fecha actual",
)
ap.add_argument(
    "--limit",
    type=int,
    help="limitar el número de resultados a extraer de Mercado Público",
)
ap.add_argument(
    "--category",
    "-c",
    choices=list(e.name for e in BidStatus) + ["*"],
    help="tipo de licitación ágil a buscar exclusivamente; '*' para todas las licitaciones",
)
ap.add_argument(
    "--save-files",
    action=argparse.BooleanOptionalAction,
    default=True,
    help="guardar los archivos extraídos de Mercado Público de forma local",
)
ap.add_argument(
    "--only-missing",
    action=argparse.BooleanOptionalAction,
    default=False,
    help="extraer solamente las licitaciones que no están en la base de datos ni en los archivos extraídos locales",
)
ap.add_argument(
    "--merge",
    action=argparse.BooleanOptionalAction,
    default=True,
    help="hacer cambios a la base de datos con los archivos extraídos",
)


def main():
    import sqlalchemy
    import sqlalchemy.orm

    args = ap.parse_args()

    con_string = args.database or DATABASE_CONNECTION
    logger.info(f"Conectado a la base de datos {con_string!r}")
    try:
        engine = sqlalchemy.create_engine(con_string)
    except Exception as err:
        logger.error(f"Error al conectar a la base de datos {con_string!r}!")
        logger.error(err)
        sys.exit(1)
    Session = sqlalchemy.orm.sessionmaker(engine)
    with Session.begin() as session:
        prepare_database(engine, session)
        ignores = get_ignores(session)

    files = {}
    if args.scrape:
        for idx, scraped in scrape(args, ignores):
            if scraped:
                files[idx] = scraped
                if args.save_files:
                    save_files({idx: scraped})
    if not files:
        files = load_files()

    with Session() as session:
        if args.merge:
            parse(session, files)
