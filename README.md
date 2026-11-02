# tools

What every rfnry repository runs and none ships: the CI gate every repository's `ci.yml` calls
(`.github/workflows/gate.yml`), the scripts it runs (`scripts/`), the `ci.yml` and the publish workflows each library
keeps a copy of (`templates/`), and the Renovate preset every repository extends (`default.json`). Pins move by hand
until Renovate is installed on the organization.
