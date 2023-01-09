# MerPubScraper

Utilidad para extraer datos (actualmente, solo licitaciones ágiles) de Mercado Público,
parsearlos y colocarlos en una base de datos.

## Pre-uso

El programa utiliza Poetry para manejar dependencias y el el ambiente virtual.
Si Poetry no está instalado, se pueden seguir las [instrucciones de instalación
en la página oficial](https://python-poetry.org/docs/).

Teniendo Poetry instalado, se tiene que instalar el ambiente virtual con las dependencias:

```sh
poetry install
```

Luego, se puede correr el programa con:

```sh
poetry run main
```

## Uso

Hay varias opciones de comando que afectan el comportamiento del programa.

Para el usar el crawler, se agrega la opción `--scrape`. También es necesario
añadir las credenciales de inicio de sesión para Mercado Público: `--login`
(el RUT) y `--password` (la contraseña). Aparte, se necesita especificar el
rango de fechas en las que buscar: se pueden especificar `--from` y `--until`
(con formato `AAAA-MM-DD`) para un rango específico, o `--days-before` con
un número `n`, para un rango desde la fecha de hoy hasta `n` días hacia atrás.
Por último, es necesario agregar la categoría en la que se va a buscar:
`"PUBLISHED"` (Publicadas), `"CLOSED"` (Cerradas), `"BO_EMITTED"` (OC Emitida),
`"CANCELLED"` (Cancelada) o bien `"*"` para todas las categorías.

La opción `--limit` permite limitar la cantidad de resultados a extraer a
un número máximo.

La opción `--no-save-files` hace que no se guarden los archivos extraídos en l
carpeta `__workdir__`. No se recomienda activar, ya que guardar los archivos
permite reanudar el trabajo de parseo en caso de error.

Si se activa `--only-missing`, las licitaciones que ya están en la base de
datos o en los archivos locales no serán tomadas en cuenta por el crawler.

Se puede omitir el paso de parseo y actualización de la base de datos con la
opción `--no-merge`.

Para especificar la base de datos a usar, se usa la opción `--database`, con
una string de conexión de SQLAlchemy: `dialecto://user:pass@host:port/database`,
por ejemplo: `postgresql://admin:1234@localhost:5432/sales`. De no
especificarse, se utilizará una base de datos SQLite en la carpeta principal.

Un ejemplo que extrae 20 resultados de Mercado Público, de licitaciones ágiles
con orden de compra emitida de los últimos 3 días:
```sh
poetry run main --scrape -l "XX.XXX.XXX-4" -p "XXXXXXXX" -c BO_EMITTED --days -before 3
```

## Notas sobre el crawler

El crawler (parte que extrae los datos de Mercado Público) es muy inestable y
propenso a fallar, por lo que es normal que termine con un error.
En ciertos casos, el crawler detectará algún error de la página y reintentará o
avisará al respecto, pero en la mayoría de los casos, se puede leer el archivo
de log (`log.txt` en el directorio principal) o los volcados de página (la
carpeta `__dump__`) para saber qué causó el problema.
