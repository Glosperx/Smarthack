"""
# Hill-zone wind resource atlas

Forecasts the mean wind over the next full years on hill terrain (200-800 m) across
Romania and proposes where a wind park would catch the most of it. Pure computation:
downloading the sources is `smarthack.clients.resource_sources`, putting it together is
`smarthack.services.resource_service`.

Import the submodules directly (`smarthack.resource.climate`, `.grid`, `.render`,
`.sites`, `.terrain`, `.constants`). The package itself exports nothing, so importing
it does not pull in numpy.
"""

__all__: list[str] = []
