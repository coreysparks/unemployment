library(brms)
load("~/unemp_ests.rds")
head(ests)
library(dplyr)
ests<-ests%>%
  filter(se!=0)%>%
  mutate(month=`factor(month)`)
#f1<-bf(emp_bin|mi(se)~race_eth2+(1|stname))
mod1<-brm(emp_bin|mi(se)~race_eth2+(1|stname/month), family=gaussian, data=ests, chains = 3, cores=3, save_mevars = TRUE)
