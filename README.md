# Safer Cycling In The City

A dashboard visualising cyclists exposure to air pollution across Tāmaki Makaurau Auckland.

This data has been collected with up to three air pollution measurements instruments (Atmotube, P-Trak, Vaisala) and a GPS recorder attached to bikes:

__GPS__
* Longitude and Latitude coordinates, sampled every second
* tracked on Strava as a fallback (irregular sampling, up to every 4 seconds or more), also recorded by Atmotube (every 60 seconds)

__Atmotube__
* VOC (ppm)
* Air Quality Score (AQS)
* Temperature (C)
* Humidity (%)
* Pressure (mbar)
* PM1 (ug/m3), PM2.5 (ug/m3), PM10 (ug/m3)

__P-Trak__
* Ultrafine Particles (pt/cc)

__Vaisala__
* CO2 (ppm)
* Gas / Sensor Temp (C)  


<br>
<br>

## Dashboard
The dashboard allows the user to explore air pollution based on time of day/ route choice. Cycling trips are classified by common routes and can be explored at the trip-level.

## Data pre-processing
For data to be displayed on the dashboard, the measurements across the different instruments had to be combined and map-matched. Map-matching is a process that allows us to... Thus, we can investigate air pollution at the road segment level.

### (1) Data cleaning
Data cleaning is required prior to data fusion to ensure no air pollution records are lost. Key quality control measures include:
* good GPS coverage;
* can handle gpx input (Strava activities), but priotises GPS data in csv format (exported from GPS recorder);
* no duplicate timestamps for any recordings (data fusion key), i.e., when measurements are taken at a one-second interval, the seconds must be recorded, too;
* ideally no empty rows/columns, though these are stripped when reading the csv file.

### (2) Data fusion
Air pollution measurements from up to three devices (Atmotube, P-Trak, Vaisala) are linked to GPS trajectories (every second) based on unix timestamp. 
* trip duration is defined by the first and last P-Trak or Vaisala measurement, depending on which instrument started recording first/ ended recording last (Atmotube and GPS recordings tend to continue after the trip has ended/start earlier);
* coarse GPS sampling rates (>1 sec) lead to data loss, as P-Trak measurements are recorded second by second and 5-second sampling rates for Vaisala - introduced a 3 second threshold to match vaisala recordings to the nearest GPS point, but losing P-Trak recordings when Strava tracks substitute GPS recordings;
* column names must be cleaned due to varying device settings over the course of data collection; 
* timestamps must be fixed (to be valid).

### (3) Map-matching and road-level-segmentation
Trajectory points are aligned with the road network using the [Leuven.MapMatching package](https://leuvenmapmatching.readthedocs.io/en/latest/), based on a Hidden Markov Model (HMM). The network graph is build on OpenStreetMap data downloaded from [Geofarbik](https://download.geofabrik.de/australia-oceania/new-zealand.html). Sampling rates and regularity impact map-matching quality - irregular Strava recordings and sampling rates of one minute (atmotube-based GPS signal) have to be handled carefully.
