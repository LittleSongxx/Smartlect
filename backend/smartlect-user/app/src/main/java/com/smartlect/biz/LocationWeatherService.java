package com.smartlect.biz;

import com.smartlect.entity.vo.LocationWeatherVO;

public interface LocationWeatherService {

    LocationWeatherVO resolve(Double latitude, Double longitude);

    void saveUserCoords(String userId, Double latitude, Double longitude, LocationWeatherVO resolved);

    LocationWeatherVO syncUserLocation(String userId, Double latitude, Double longitude);
}
