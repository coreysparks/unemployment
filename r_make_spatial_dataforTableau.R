library(sf)
library(dplyr)
library(tigris)
library(ggplot2)
spdat<-st_read("~/Documents/cb_2018_us_state_20m.shp")
rates<-read.csv("~/Documents/GitHub/unemployment/fig_state_race.csv", header = T)

mdat<-merge(spdat, rates, by.x="NAME", by.y="stname" )

mdat%>%
  filter(race_eth2=="Black.Not Latino", month=="2020-05-01")%>%
  ggplot()+geom_sf(aes(fill=emprate))+
  coord_sf(crs =7603)

st_write(mdat, "~/Documents/unempshp.shp")
