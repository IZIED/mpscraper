from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import json
from typing import Mapping, Sequence, TypedDict

from mpscraper.application import AgilCrawlContents
from mpscraper.models import *
from mpscraper.util import Money
from mpscraper.validators import (
    normalize_full_name,
    validate_cl_phone_number,
    validate_email_address,
    validate_rut,
)

MP_DATETIME_FORMAT = r"%d-%m-%Y %H:%M:%S"
MP_DATE_FORMAT = r"%d-%m-%Y"


def money_from_compound(currency: str, amount: str | int | float):
    currency = "clp" if currency == "$" else currency.lower()
    amount_dec = Decimal(amount.replace(".", "") if isinstance(amount, str) else amount)
    return Money(amount_dec, currency)


class ParseAgilResultModels(TypedDict):
    bid: Bid
    product_types: Mapping[int, ProductType]
    person: Person
    organization_names: Sequence[OrganizationName]
    organizations: Sequence[Organization]


def parse_agil_into_db_model(agil: AgilCrawlContents) -> ParseAgilResultModels:
    """Parsea los contenidos de los archivos extraídos de una licitación ágil y
    genera los modelos para la base de datos."""
    import bs4
    import pandas

    # Extracción de los datos de la página de la licitación
    main_soup = bs4.BeautifulSoup(agil.main, "html.parser")
    (
        title,
        summary,
        published_at,
        closed_at,
        time_limit,
        sum_currency,
        sum_amount,
        contact_names,
        contact_phone_number,
        contact_email_address,
        organization_name,
        organization_rut,
        idn,
        status,
    ) = text_by_id(
        main_soup,
        (
            "lblTextName",
            "lblTextDescription",
            "lblFechaPublicacion",
            "lblFechaCierre",
            "lblPlazoEntrega",
            "lblMonedaSymbol",
            "lblMontoTotalDisponible",
            "lblDescContacto",
            "lblDescTelefono",
            "lblDescEmail",
            "lblNombreOrganismo",
            "lblRutOrganismo",
            "lblExternalCodeQuote",
            "lblrstStatus",
        ),
    )

    # Busca los productos de la licitación
    products = []
    product_types = {}
    if table := main_soup.find(id="gvCategory"):
        for row in table.find_all(class_="dccp-row"):  # type: ignore
            product_name_info, product_summary, product_amount = row.find_all("td")
            product_name = product_name_info.find(class_="d-block").text
            product_type = product_name_info.find(class_="text-gray").text.split(" ")[1]
            product_type = int(product_type)
            product_summary = product_summary.text
            product_amount = int(float(product_amount.find(class_="text-font-15").text))
            product_type = product_types.setdefault(
                product_type, ProductType(code=product_type, name=product_name)
            )
            products.append(
                Product(
                    type_code=product_type.code,
                    amount=product_amount,
                    title=product_summary,
                )
            )

    published_at = datetime.strptime(published_at, MP_DATETIME_FORMAT)
    closed_at = datetime.strptime(closed_at, MP_DATETIME_FORMAT)
    organization_rut = validate_rut(organization_rut, dotted=False)
    organization_name_model = OrganizationName(
        name=organization_name, organization_rut=organization_rut
    )
    organizations_names = [organization_name_model]
    organization = Organization(rut=organization_rut)
    organizations = [organization]
    sum = money_from_compound(sum_currency, sum_amount)
    contact_phone_number = validate_cl_phone_number(contact_phone_number, lenient=True)
    contact_email_address = validate_email_address(contact_email_address, lenient=True)
    contact_names, contact_surnames = normalize_full_name(contact_names)
    # Contacto es la persona que se lista en la info lateral de la licitación
    contact = Person(
        names=contact_names,
        surnames=contact_surnames,
        phone_numbers=[PersonPhoneNumber(number=contact_phone_number)]
        if contact_phone_number
        else [],
        email_addresses=[PersonEmailAddress(address=contact_email_address)]
        if contact_email_address
        else [],
    )

    # Procesa los modales junto a la lista de proveedores (xls/html)
    applications = []
    if agil.modals and agil.provider_listing:
        # En caso de que ya haya un proveedor seleccionado
        if agil.modal_selected:
            selected_rut = validate_rut(main_soup.find(id="gvSeleccionado").find(class_="declaracion-rutRazonSocial").text)  # type: ignore
        else:
            selected_rut = None

        import pandas

        df_applications = pandas.read_html(
            agil.provider_listing.content, header=0, decimal=",", thousands="."
        )[0]
        df_applications.rename(
            {
                "Cotizacion": "i",
                "Orden": "j",
                "Rut Proveedor": "organization_rut",
                "Razon Social": "organization_name",
                "Nombre Producto": "product_name",
                "Detalle Producto": "product_summary",
                "Cantidad": "amount",
                "Moneda": "sum_currency",
                "Precio Unitario": "sum_per_unit",
                "Total Impuestos": "sum_taxed",
                "Monto Total Cotizacion": "sum_total",
                "Codigo Solicitud Cotizacion": "bid_idn",
            },
            inplace=True,
            axis=1,
        )
        # Al procesar la lista de proveedores, es necesario agrupar en grupos de j + 1,
        # donde j es el valor de la columna "Orden" más alto
        # Cada grupo contiene primero una fila con contenido general, y luego los
        # productos a los que postula la licitación
        groupby = df_applications["j"].max() + 1
        groupby = df_applications.groupby(df_applications.index // groupby)

        assert len(agil.modals) == len(groupby)

        for modal, sheet in zip(agil.modals, groupby):
            modal = json.loads(modal)[
                "d"
            ]  # el json es un json {"d": "..."}, donde "..." es otro json
            modal = json.loads(modal)

            # Saca la fecha de envío y descripción del json del modal
            sent_at = modal["FechaEnvio"]
            product_summary = modal["Descripcion"]
            sent_at = datetime.strptime(sent_at, MP_DATE_FORMAT).date()

            # entrega un dataframe como lista de diccionarios
            sheet = sheet[1].to_dict("records")
            total_row = sheet[0]
            organization_name = total_row["organization_name"]
            organization_rut = validate_rut(total_row["organization_rut"])
            sum_currency = total_row["sum_currency"]
            total_sum = total_row["sum_total"]
            total_sum = money_from_compound(sum_currency, total_sum)

            # Procesa los productos de la postulación
            application_products = []
            for idx, sheet_product_row in enumerate(sheet[1:]):  # type: ignore
                sum_amount = sheet_product_row["sum_per_unit"]
                sum = money_from_compound(sum_currency, sum_amount)
                application_products.append(
                    ApplicationProduct(sum=sum, product=products[idx])
                )

            application_organization = OrganizationName(
                organization_rut=organization_rut, name=organization_name
            )
            application_organization_rut = organization_rut
            organizations.append(Organization(rut=application_organization_rut))
            organizations_names.append(application_organization)
            if selected_rut is not None:
                selected = selected_rut == application_organization_rut
            else:
                selected = None
            application = Application(
                products=application_products,
                summary=product_summary,
                organization=application_organization,
                total_sum=total_sum,
                accepted=selected,
                sent_at=sent_at,
            )
            applications.append(application)

    bid = Bid(
        type=BidType.AGIL,
        idn=idn,
        title=title,
        summary=summary,
        published_at=published_at,
        closed_at=closed_at,
        organization=organization_name_model,
        sum=sum,
        products=products,
        contact=contact,
        status=str_to_bid_status(status),
    )
    for application in applications:
        application.bid = bid

    return ParseAgilResultModels(
        bid=bid,
        product_types=product_types,
        person=contact,
        organization_names=organizations_names,
        organizations=organizations,
    )


def text_by_id(soup, ids: Sequence[str]):
    """Busca un elemento por cada id entregada y retorna el contenido de texto
    de cada elemento encontrado en ese orden."""
    elements = []
    for id in ids:
        element = soup.find(id=id)
        elements.append(element)
    return [element and element.text for element in elements]


class AgilSearchResult(TypedDict):
    idn: str
    name: str
    buying_unit: str
    published_at: datetime
    closed_at: datetime
    status: str


def str_to_bid_status(value: str):
    match value:
        case "OC Emitida":
            return BidStatus.BO_EMITTED
        case "Cerrada":
            return BidStatus.CLOSED
        case "Cancelada":
            return BidStatus.CANCELLED
        case "Publicada":
            return BidStatus.PUBLISHED
    return None


def parse_agil_search_results_html(src: str) -> Mapping[str, AgilSearchResult]:
    """Parsea los contenidos del xls/html de los resultados de una búsqueda de licitación."""
    import pandas

    df = pandas.read_html(src, header=0, parse_dates=[3, 4])[0]
    df.rename(
        {
            "ID": "idn",
            "Nombre": "name",
            "Unidad de compra": "buying_unit",  # ?
            "Fecha de publicación": "published_at",
            "Fecha de cierre": "closed_at",
            "Estado": "status",
            "Cotizaciones enviadas": "sent_biddings",
            "Institución": "organization_name",
        },
        inplace=True,
        axis=1,
    )

    results = {row["idn"]: row for row in df.to_dict("records")}
    for idn, row in results.items():
        row["published_at"] = row["published_at"].to_pydatetime()
        row["closed_at"] = row["closed_at"].to_pydatetime()
        row["status"] = str_to_bid_status(row["status"])
    return results  # type: ignore
