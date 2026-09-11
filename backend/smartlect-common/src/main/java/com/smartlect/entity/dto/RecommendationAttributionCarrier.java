package com.smartlect.entity.dto;

import java.util.Date;

/**
 * Optional recommendation touchpoint carried through cart and order commands.
 * Implementations must treat source/time as server-owned canonical fields.
 */
public interface RecommendationAttributionCarrier {

    String getProductId();

    String getPropertyValueIdHash();

    String getRecommendationRequestId();

    void setRecommendationRequestId(String recommendationRequestId);

    Integer getRecommendationPosition();

    void setRecommendationPosition(Integer recommendationPosition);

    String getRecommendationSource();

    void setRecommendationSource(String recommendationSource);

    Date getRecommendationAttributedAt();

    void setRecommendationAttributedAt(Date recommendationAttributedAt);

    default void clearRecommendationAttribution() {
        setRecommendationRequestId(null);
        setRecommendationPosition(null);
        setRecommendationSource(null);
        setRecommendationAttributedAt(null);
    }
}
