library(haven)
library(ipumsr)

ddi<- read_ipums_ddi(ddi_file = "~/OneDrive - University of Texas at San Antonio/projects/carsey_brief/cps_00037.xml")
cpsdat<-read_ipums_micro(ddi)
cpsdat<-zap_labels(cpsdat)
save(cpsdat, file="~/OneDrive - University of Texas at San Antonio/projects/carsey_brief/cpsbriefdata.Rdata")
#write_sas(cpsdat, path = "~/OneDrive - University of Texas at San Antonio/projects/carsey_brief/cpsbriefdata.sas7bdat")
