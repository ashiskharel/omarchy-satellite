# Satellite

An [Omarchy](https://omarchy.org) bar plugin. It sits beside the weather widget and tells you which of three satellites is worth looking up for: the ISS, Hubble, and Tiangong.

The bar stays quiet.

- Overhead: `ISS 42°`
- Nothing overhead, a pass coming: `HST 14m`
- Nothing soon: a dim dash

Click the label for elevation, azimuth, whether it is rising or setting, and the next pass. The circle is your sky: the center is straight overhead, the rim is the horizon, and north is up. **Ping** asks CelesTrak for fresh orbits and recomputes the angles from where you are. It does not transmit anything.

Orbits come from [CelesTrak](https://celestrak.org). Your coordinates stay on this machine. If the weather widget has a latitude and longitude, those are used. Otherwise the plugin uses the city of your network connection.

## Install

```sh
omarchy plugin add https://github.com/ashiskharel/omarchy-satellite.git --enable --yes
```

That puts it in the center of the bar. Drag it next to the weather, or move it:

```sh
omarchy bar put ashis.satellite --after omarchy.weather
```

Middle-click or right-click the label to ping without opening the panel.

## Remove

```sh
omarchy plugin remove ashis.satellite
```

That disables the plugin and deletes the installed copy. The rest of the bar stays as it is.

The orbit math is the MIT-licensed [sgp4](https://pypi.org/project/sgp4/) library, included under `vendor/sgp4` as pure Python. Its license is `vendor/sgp4/LICENSE`.
