package com.smartlect.mappers;

import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;
import org.apache.ibatis.annotations.Select;
import java.math.BigDecimal;

import java.util.List;
import java.util.Map;

public interface OrderItemMapper<T,P> extends BaseMapper<T,P> {

    @Update("""
            UPDATE order_item SET paid_amount = #{paidAmount}
            WHERE order_item_id = #{orderItemId}
              AND paid_amount IS NULL
              AND #{paidAmount} >= refunded_amount
            """)
    int recordPaidAmount(@Param("orderItemId") String orderItemId,
                         @Param("paidAmount") BigDecimal paidAmount);

    // ponytail: aggregate history on demand; add product/payment indexes when measured volume requires them.
    @Select("""
            <script>
            SELECT candidate.product_id
            FROM order_item seed
            JOIN order_info seed_order ON seed_order.order_id = seed.order_id
            JOIN order_info candidate_order
              ON candidate_order.pay_order_id = seed_order.pay_order_id
             AND candidate_order.user_id = seed_order.user_id
            JOIN order_item candidate ON candidate.order_id = candidate_order.order_id
            WHERE seed.product_id = #{productId}
              AND seed_order.pay_order_id IS NOT NULL AND seed_order.pay_order_id &lt;&gt; ''
              AND seed_order.order_status IN (1, 2, 3, 7, 8)
              AND candidate_order.order_status IN (1, 2, 3, 7, 8)
              AND seed.order_item_status = 1 AND candidate.order_item_status = 1
              AND seed.paid_amount IS NOT NULL AND candidate.paid_amount IS NOT NULL
              AND candidate.product_id &lt;&gt; #{productId}
            <if test="productIds != null">
              <choose>
                <when test="productIds.size() == 0">AND 1 = 0</when>
                <otherwise>
                  AND candidate.product_id IN
                  <foreach item="id" collection="productIds" open="(" separator="," close=")">#{id}</foreach>
                </otherwise>
              </choose>
            </if>
            <if test="excludeProductIds != null and excludeProductIds.size() &gt; 0">
              AND candidate.product_id NOT IN
              <foreach item="id" collection="excludeProductIds" open="(" separator="," close=")">#{id}</foreach>
            </if>
            GROUP BY candidate.product_id
            ORDER BY COUNT(DISTINCT seed_order.pay_order_id) DESC, candidate.product_id ASC
            LIMIT #{limit}
            </script>
            """)
    List<String> selectCoPurchaseProductIds(@Param("productId") String productId,
                                          @Param("productIds") List<String> productIds,
                                          @Param("excludeProductIds") List<String> excludeProductIds,
                                          @Param("limit") int limit);

    // Historical confirmed payment units include zero-paid lines and later refunds.
    // ponytail: aggregate existing facts on demand; add measured indexes before introducing a counter cache.
    @Select("""
            <script>
            SELECT item.product_id AS productId, SUM(item.buy_count) AS paidUnits
            FROM order_item item JOIN order_info orders ON orders.order_id = item.order_id
            WHERE item.paid_amount IS NOT NULL AND item.buy_count &gt; 0
              AND orders.pay_order_id IS NOT NULL AND TRIM(orders.pay_order_id) &lt;&gt; ''
              AND orders.user_id IS NOT NULL AND TRIM(orders.user_id) &lt;&gt; ''
              AND NOT EXISTS (
                SELECT 1 FROM order_info other_order
                WHERE other_order.pay_order_id = orders.pay_order_id
                  AND (other_order.user_id IS NULL OR other_order.user_id &lt;&gt; orders.user_id)
              )
            <if test="productIds != null">
              <choose>
                <when test="productIds.size() == 0">AND 1 = 0</when>
                <otherwise>
                  AND item.product_id IN
                  <foreach item="id" collection="productIds" open="(" separator="," close=")">#{id}</foreach>
                </otherwise>
              </choose>
            </if>
            <if test="excludeProductIds != null and excludeProductIds.size() &gt; 0">
              AND item.product_id NOT IN
              <foreach item="id" collection="excludeProductIds" open="(" separator="," close=")">#{id}</foreach>
            </if>
            GROUP BY item.product_id
            ORDER BY paidUnits DESC, item.product_id ASC
            LIMIT #{limit}
            </script>
            """)
    List<Map<String, Object>> selectPopularProducts(@Param("productIds") List<String> productIds,
            @Param("excludeProductIds") List<String> excludeProductIds, @Param("limit") int limit);

	 Integer updateByOrderItemId(@Param("bean") T t,@Param("orderItemId") String orderItemId);

	 Integer deleteByOrderItemId(@Param("orderItemId") String orderItemId);

	 T selectByOrderItemId(@Param("orderItemId") String orderItemId);

	 T selectByOrderItemIdForUpdate(@Param("orderItemId") String orderItemId);

	 Integer countNormalByOrderId(@Param("orderId") String orderId);

	 List<T> selectByOrderIds(@Param("orderIds") List<String> orderIds);

	 Integer countPriorSuccessfulPurchases(
			 @Param("userId") String userId,
			 @Param("productId") String productId,
			 @Param("excludedOrderIds") List<String> excludedOrderIds,
			 @Param("successfulStatuses") List<Integer> successfulStatuses);

}
