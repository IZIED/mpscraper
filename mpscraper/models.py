from __future__ import annotations

import enum
from datetime import datetime, timedelta

import sqlalchemy.sql.functions
from sqlalchemy import Column, ForeignKey, MetaData, String, Table
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    composite,
    mapped_column,
    relationship,
)

from mpscraper.util import IntEnum, Money


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class WithTimestamps:
    created_at: Mapped[datetime] = mapped_column(
        server_default=sqlalchemy.sql.functions.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=sqlalchemy.sql.functions.now(),
        onupdate=sqlalchemy.sql.functions.now(),
    )


class Currency(Base):
    __tablename__ = "currency"

    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)

    def __repr__(self):
        return f"Currency({self.code!r}, {self.name!r})"


class Region(Base):
    __tablename__ = "region"

    code: Mapped[int] = mapped_column(unique=True, primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    long_name: Mapped[str | None] = mapped_column()
    cities: Mapped[list[City]] = relationship(back_populates="region")

    def __repr__(self):
        return f"Region({self.name!r}, code={self.code!r})"


class City(Base):
    __tablename__ = "city"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column()
    region_code: Mapped[int] = mapped_column(ForeignKey(Region.code))
    region: Mapped[Region] = relationship(back_populates="cities")

    def __repr__(self):
        return f"City({self.name!r}, {self.region!r})"


class Address(Base):
    __tablename__ = "address"

    id: Mapped[int] = mapped_column(primary_key=True)
    address: Mapped[str] = mapped_column()
    city_id: Mapped[int] = mapped_column(ForeignKey(City.id))
    city: Mapped[City] = relationship()
    extra: Mapped[str | None] = mapped_column()

    def __repr__(self):
        return f"Address({self.address!r}, {self.city!r})"


_Person_tablename = "person"
_Organization_tablename = "organization"

person_organization_table = Table(
    "person_organization",
    Base.metadata,
    Column("person_id", ForeignKey(_Person_tablename + ".id"), primary_key=True),
    Column(
        "organization_rut",
        ForeignKey(_Organization_tablename + ".rut"),
        primary_key=True,
    ),
)


class Person(WithTimestamps, Base):
    __tablename__ = _Person_tablename

    id: Mapped[int] = mapped_column(primary_key=True)
    rut: Mapped[str | None] = mapped_column(unique=True)
    names: Mapped[str] = mapped_column()
    surnames: Mapped[str] = mapped_column()
    bids: Mapped[list[Bid]] = relationship(back_populates="contact")
    organizations: Mapped[list[Organization]] = relationship(
        back_populates="contacts", secondary=person_organization_table
    )
    email_addresses: Mapped[list[PersonEmailAddress]] = relationship(
        back_populates="person"
    )
    phone_numbers: Mapped[list[PersonPhoneNumber]] = relationship(
        back_populates="person"
    )

    def __repr__(self):
        return f"Person({self.names!r}, {self.surnames!r}, rut={self.rut!r})"


class PersonEmailAddress(Base):
    __tablename__ = "person_email_address"

    id: Mapped[int] = mapped_column(primary_key=True)
    address: Mapped[str] = mapped_column()
    person_id: Mapped[int] = mapped_column(ForeignKey(Person.id))
    person: Mapped[Person] = relationship(back_populates="email_addresses")
    detail: Mapped[str | None] = mapped_column()

    def __repr__(self):
        return f"PersonEmailAddress({self.address!r}, entity={self.person!r}, detail={self.detail!r})"


class PersonPhoneNumber(Base):
    __tablename__ = "entity_phone_number"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(16))
    person_id: Mapped[int] = mapped_column(ForeignKey(Person.id))
    person: Mapped[Person] = relationship(back_populates="phone_numbers")
    detail: Mapped[str | None] = mapped_column()

    def __repr__(self):
        return f"PersonPhoneNumber({self.number!r}, entity={self.person!r}, detail={self.detail!r})"


class Organization(WithTimestamps, Base):
    __tablename__ = _Organization_tablename

    rut: Mapped[str] = mapped_column(primary_key=True, unique=True)
    canonical_name: Mapped[str | None] = mapped_column()
    names: Mapped[list[OrganizationName]] = relationship(back_populates="organization")

    contacts: Mapped[list[Person]] = relationship(
        back_populates="organizations", secondary=person_organization_table
    )

    def __repr__(self):
        return f"Organization({self.rut!r})"


class OrganizationName(WithTimestamps, Base):
    __tablename__ = "organization_name"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str | None] = mapped_column()
    organization_rut: Mapped[int] = mapped_column(ForeignKey(Organization.rut))
    organization: Mapped[Organization] = relationship(back_populates="names")
    applications: Mapped[Application] = relationship(back_populates="organization")

    def __repr__(self):
        return f"OrganizationName({self.name!r}, organization={self.organization!r})"


class BidType(enum.IntEnum):
    REGULAR = 1
    AGIL = 2


class BidStatus(enum.IntEnum):
    PUBLISHED = 1
    CLOSED = 2
    BO_EMITTED = 3
    CANCELLED = 4


class Bid(WithTimestamps, Base):
    """Modelo de una licitación."""

    __tablename__ = "bid"

    idn: Mapped[str] = mapped_column(primary_key=True)
    status: Mapped[BidStatus] = mapped_column(IntEnum(BidStatus))
    published_at: Mapped[datetime | None]
    closed_at: Mapped[datetime | None]
    title: Mapped[str] = mapped_column()
    summary: Mapped[str | None] = mapped_column()
    sum: Mapped[Money] = composite(
        mapped_column("sum_amount"),
        mapped_column("sum_currency", ForeignKey(Currency.code)),
    )
    time_limit: Mapped[timedelta | None] = mapped_column()
    type: Mapped[BidType] = mapped_column(IntEnum(BidType))
    address_id: Mapped[int | None] = mapped_column(ForeignKey(Address.id))
    address: Mapped[Address | None] = relationship()
    organization_id: Mapped[int] = mapped_column(ForeignKey(OrganizationName.id))
    organization: Mapped[OrganizationName] = relationship()
    products: Mapped[list[Product]] = relationship(back_populates="bid")
    contact_id: Mapped[int | None] = mapped_column(ForeignKey(Person.id))
    contact: Mapped[Person | None] = relationship(back_populates="bids")
    buying_order: Mapped[BuyingOrder | None] = relationship(back_populates="bid")
    applications: Mapped[list[Application]] = relationship(back_populates="bid")

    def __repr__(self):
        return (
            f"Bid({self.title!r}, idn={self.idn!r}, published_at={self.published_at!r})"
        )


class ProductType(Base):
    __tablename__ = "product_type"

    code: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column()

    def __repr__(self):
        return f"ProductType({self.name!r}, code={self.code!r})"


class Product(WithTimestamps, Base):
    """Modelo de un producto o "línea" asociada a una licitación."""

    __tablename__ = "product"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column()
    amount: Mapped[int | None] = mapped_column(default=1)
    type_code: Mapped[int] = mapped_column(ForeignKey(ProductType.code))
    type: Mapped[ProductType] = relationship()
    bid_idn: Mapped[str] = mapped_column(ForeignKey(Bid.idn))
    bid: Mapped[Bid] = relationship(back_populates="products")
    applications: Mapped[list[ApplicationProduct]] = relationship(
        back_populates="product"
    )

    def __repr__(self):
        return f"Product({self.title!r}, {self.type!r}, bid={self.bid!r})"


class Application(WithTimestamps, Base):
    """Modelo de una postulación de un organismo a una línea de una licitación."""

    __tablename__ = "application"

    id: Mapped[int] = mapped_column(primary_key=True)
    sent_at: Mapped[datetime | None] = mapped_column()
    summary: Mapped[str | None] = mapped_column()
    accepted: Mapped[bool | None]
    bid_idn: Mapped[str] = mapped_column(ForeignKey(Bid.idn))
    bid: Mapped[Bid] = relationship(back_populates="applications")
    organization_id: Mapped[int] = mapped_column(ForeignKey(OrganizationName.id))
    organization: Mapped[OrganizationName] = relationship(back_populates="applications")
    products: Mapped[list[ApplicationProduct]] = relationship(
        back_populates="application"
    )
    total_sum: Mapped[Money] = composite(
        mapped_column("total_sum_amount"),
        mapped_column("total_sum_currency", ForeignKey(Currency.code)),
    )

    def __repr__(self):
        return (
            f"Application(organization={self.organization!r}, summary={self.summary!r})"
        )


class ApplicationProduct(WithTimestamps, Base):
    """Modelo de una postulación a un producto."""

    __tablename__ = "application_product"

    id: Mapped[int] = mapped_column(primary_key=True)
    sum: Mapped[Money] = composite(
        mapped_column("sum_amount"), mapped_column("sum_currency", ForeignKey(Currency.code))  # type: ignore
    )
    product_id: Mapped[int] = mapped_column(ForeignKey(Product.id))
    product: Mapped[Product] = relationship(back_populates="applications")
    application_id: Mapped[int] = mapped_column(ForeignKey(Application.id))
    application: Mapped[Application] = relationship(back_populates="products")


class BuyingOrder(WithTimestamps, Base):
    """Modelo de una orden de compra."""

    __tablename__ = "buying_order"

    id: Mapped[int] = mapped_column(primary_key=True)
    idn: Mapped[str] = mapped_column(unique=True)
    bid_idn: Mapped[str] = mapped_column(ForeignKey(Bid.idn))
    bid: Mapped[Bid] = relationship(back_populates="buying_order")
    application_id: Mapped[int] = mapped_column(ForeignKey(Application.id))
    application: Mapped[Application] = relationship()
    published_at: Mapped[datetime | None] = mapped_column()
    notes: Mapped[str | None] = mapped_column()

    def __repr__(self):
        return f"BuyingOrder(idn={self.idn!r}, published_at={self.published_at!r})"


def init_database(session: Session):
    from sqlalchemy import select
    from mpscraper.static import regions, cities, currency

    region_models = {
        code: Region(name=name, code=code, long_name=long_name)
        for name, code, long_name in regions
    }
    city_models = [
        City(name=name, region_code=region_code) for region_code, name in cities
    ]
    for value in region_models.values():
        session.merge(value)
    cities_already_in = [city.name for city in session.scalars(select(City)).all()]

    for value in city_models:
        if value.name not in cities_already_in:
            session.add(value)

    for unit, name in currency:
        session.merge(Currency(code=unit, name=name))
