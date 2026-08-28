# Guía rápida Noria — odoo-mcp-19

Servidor MCP para que Claude (Code o Desktop) lea y escriba datos de una instancia **Odoo 19+**
en lenguaje natural, con capa de seguridad para operaciones destructivas. Este es el fork de
Noria ([noriadigital/odoo-mcp-19](https://github.com/noriadigital/odoo-mcp-19)); el proyecto
original es [AlanOgic/odoo-mcp-19](https://github.com/AlanOgic/odoo-mcp-19).

Esta guía es el camino mínimo para tenerlo andando. El [README.md](README.md) completo
documenta todo lo demás (transporte HTTP, modo multi-usuario, capa de seguridad, etc.).

## Requisitos

- **Docker** (Docker Desktop en Mac/Windows, o el daemon en Linux/WSL).
- Una instancia **Odoo 19+** con acceso API.
- Una **API key** de tu usuario de Odoo: en Odoo, *Preferencias → Seguridad de la cuenta →
  Nueva clave API*.

## Instalación (una sola vez)

```bash
# 1. Clonar el fork de Noria
git clone https://github.com/noriadigital/odoo-mcp-19.git
cd odoo-mcp-19

# 2. Credenciales: copiar la plantilla y completar los 4 valores requeridos
cp .env.example .env
```

Editar `.env` — con esto alcanza (el resto es opcional):

```bash
ODOO_URL=https://tu-instancia.odoo.com
ODOO_DB=tu-base
ODOO_USERNAME=tu-usuario@ejemplo.com
ODOO_API_KEY=la-api-key-generada-en-odoo
```

> `.env` está gitignorado: las credenciales nunca se commitean. Cada persona usa su propia
> API key, así los cambios en Odoo quedan registrados a su nombre.

```bash
# 3. Buildear la imagen (el nombre odoo-mcp-19:latest es el que espera run-docker.sh)
docker build -t odoo-mcp-19:latest .

# 4. Probar que conecta: imprime un banner con la URL/db/usuario y queda esperando (Ctrl-C)
./run-docker.sh
```

## Registrarlo en Claude

> Registrarlo siempre con el nombre **`odoo19-mcp`** — los ejemplos y skills asumen ese nombre.

**Claude Code** (lo más simple, desde cualquier proyecto):

```bash
claude mcp add odoo19-mcp -- /ruta/absoluta/a/odoo-mcp-19/run-docker.sh
```

o declararlo en el `.mcp.json` del proyecto (para compartirlo con el equipo del repo):

```json
{
  "mcpServers": {
    "odoo19-mcp": {
      "command": "/ruta/absoluta/a/odoo-mcp-19/run-docker.sh"
    }
  }
}
```

**Claude Desktop**: mismo bloque JSON dentro de `mcpServers` en su archivo de configuración
(macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`; Windows:
`%APPDATA%\Claude\claude_desktop_config.json`), y reiniciar la app.

## Verificar

Pedirle a Claude: *"Listame los primeros 5 partners de Odoo"*. Debería llamar a
`execute_method` sobre `res.partner` y devolver nombres reales de la instancia.

## Notas de uso

- **Lecturas** (search, read, search_read...) salen directo. **Escrituras y operaciones
  riesgosas** quedan retenidas por la capa de seguridad detrás de un token de confirmación de
  un solo uso — Claude te va a pedir confirmación antes de ejecutarlas.
- `search_read` devuelve como máximo **1000 registros por llamada**; para conjuntos grandes hay
  que paginar con `offset` hasta cubrir `search_count`.
- Para apuntar a otra instancia de Odoo alcanza con cambiar el `.env` (no hace falta rebuild).

## Actualizar

```bash
git pull                                  # traer cambios del fork de Noria
docker build -t odoo-mcp-19:latest .      # rebuildear la imagen
```

Los mantenedores del fork traen las novedades del proyecto original con
`git fetch upstream && git merge upstream/master` (remote `upstream` =
AlanOgic/odoo-mcp-19).
