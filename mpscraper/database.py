from sqlalchemy import select
from sqlalchemy.orm import Session

from mpscraper.models import *
from mpscraper.parser import ParseAgilResultModels


# Colocar acá la lógica a tomar cuando se agregan nuevos modelos en la
# base datos. Por ejemplo, resolver conflictos de ID, modificar o agregar
# filas, etc
def merge_agil_models_into_db(session: Session, models: ParseAgilResultModels):
    """Agrega y/o modifica modelos en la base de datos a base de los
    modelos de un parseo de una licitación ágil."""
    product_types = models["product_types"]
    for product_type in product_types.values():
        session.merge(product_type)

    for organization in models["organizations"]:
        session.merge(organization)
    bid = models["bid"]
    already_in = session.execute(select(Bid).where(Bid.idn == bid.idn))
    if old_bid := already_in.first():
        pass  # todo: merging logic?
    else:
        session.add(models["bid"])
