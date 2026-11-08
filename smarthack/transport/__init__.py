"""
# Oversize transport network

Judges every major road of Romania for the oversize loads of a 2.4-3 MW wind turbine
(60 m blade, 4.8 m high tower section, 120 t nacelle transport) and says which roads a
convoy can reach from the entry ports. Pure computation: downloading the OSM extract is
`smarthack.clients.transport_sources`, putting it together is
`smarthack.services.transport_service`.

Import the submodules directly (`smarthack.transport.constants`, `.geometry`, `.network`,
`.osm`, `.rules`). The package itself exports nothing, so importing it does not pull in
numpy or osmium.
"""

__all__: list[str] = []
