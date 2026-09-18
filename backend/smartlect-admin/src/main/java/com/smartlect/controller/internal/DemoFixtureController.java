package com.smartlect.controller.internal;

import com.smartlect.component.RedisComponent;
import com.smartlect.controller.ABaseController;
import com.smartlect.entity.dto.TokenUserInfoDTO;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.exception.BusinessException;
import com.smartlect.service.PasswordService;
import com.smartlect.utils.StringTools;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;

import java.math.BigDecimal;
import java.util.Map;

/** Local fixture initialization stays inside Java's commerce authority. */
@RestController
@RequestMapping("/internal/demo")
@ConditionalOnProperty(name = "smartlect.demo.enabled", havingValue = "true")
public class DemoFixtureController extends ABaseController {
    private final JdbcTemplate jdbc;
    private final PasswordService passwords;
    private final RedisComponent redis;
    private final String password;

    public DemoFixtureController(JdbcTemplate jdbc, PasswordService passwords, RedisComponent redis,
                                 @Value("${smartlect.demo.password:}") String password,
                                 @Value("${smartlect.payment.mode:mock}") String paymentMode) {
        if (password.length() < 24 || !"mock".equals(paymentMode)) {
            throw new IllegalStateException("Demo fixtures require a generated password and mock payment mode");
        }
        this.jdbc = jdbc;
        this.passwords = passwords;
        this.redis = redis;
        this.password = password;
    }

    @PostMapping("/seed")
    @Transactional(rollbackFor = Exception.class)
    public ResponseVO seed() {
        String hash = passwords.encode(password);
        for (int i = 0; i < 100; i++) {
            String id = userId(i);
            jdbc.update("INSERT IGNORE INTO smartlect_user.user_info "
                    + "(user_id,nick_name,email,password,sex,join_time,status) VALUES (?,?,?,?,2,NOW(),1)",
                    id, "Smartlect用户" + i, id + "@demo.smartlect.local", hash);
            jdbc.update("INSERT INTO smartlect_user.user_address "
                    + "(address_id,user_id,address,addressee,phone,default_type) VALUES (?,?,?,?,?,1) AS incoming "
                    + "ON DUPLICATE KEY UPDATE address=incoming.address, addressee=incoming.addressee, "
                    + "phone=incoming.phone, default_type=1",
                    "SD" + id, id, "北京市海淀区中关村大街1号 智选模拟收货处", "模拟用户" + i, "13800000000");
        }
        String[] categories = {"数码", "家居", "运动", "阅读"};
        for (int i = 0; i < categories.length; i++) {
            jdbc.update("INSERT IGNORE INTO smartlect_product.sys_category "
                    + "(category_id,category_name,p_category_id,sort) VALUES (?,?,'0',?)",
                    "9" + i, categories[i], i);
        }
        for (int i = 0; i < 20; i++) {
            String id = String.format("%015d", 910000000000000L + i);
            BigDecimal price = BigDecimal.valueOf(1000L + i * 325L, 2);
            jdbc.update("INSERT IGNORE INTO smartlect_product.product_info "
                    + "(product_id,product_name,product_desc,create_time,category_id,p_category_id,status,min_price,max_price,total_sale,commend_type) "
                    + "VALUES (?,?,?,NOW(),?,'0',1,?,?,0,0)", id, "Smartlect" + categories[i % 4] + i,
                    "确定性合成商品，无预置销量", "9" + (i % 4), price, price.add(new BigDecimal("1.50")));
            for (int spec = 0; spec < 2; spec++) {
                String valueId = String.format("%015d", 920000000000000L + i * 10L + spec);
                String skuHash = StringTools.encodeByMD5(valueId);
                jdbc.update("INSERT IGNORE INTO smartlect_product.product_property_value "
                        + "(product_id,property_id,property_name,property_sort,cover_type,property_value_id,property_value,sort) "
                        + "VALUES (?,'9000','规格',0,0,?,?,?)", id, valueId, spec == 0 ? "标准" : "加大", spec);
                jdbc.update("INSERT IGNORE INTO smartlect_product.product_sku "
                        + "(product_id,property_value_id_hash,property_value_ids,price,sort) VALUES (?,?,?,?,?)",
                        id, skuHash, valueId, price.add(BigDecimal.valueOf(spec * 150L, 2)), spec);
                // Replaying initialization never refills an existing SKU.
                jdbc.update("INSERT IGNORE INTO smartlect_stock.sku_stock "
                        + "(product_id,property_value_id_hash,stock) VALUES (?,?,?)", id, skuHash, 5 + i);
            }
        }
        return getSuccessResponseVO(Map.of("users", 100, "products", 20, "skus", 40));
    }

    @PostMapping("/session")
    public ResponseVO session(@RequestParam int userIndex, @RequestParam String password) {
        String id = userId(userIndex);
        var hashes = jdbc.queryForList(
                "SELECT password FROM smartlect_user.user_info WHERE user_id=? AND status=1", String.class, id);
        if (hashes.isEmpty() || !passwords.matches(password, hashes.get(0))) {
            throw new BusinessException("模拟账号或密码无效");
        }
        TokenUserInfoDTO session = new TokenUserInfoDTO();
        session.setUserId(id);
        session.setEmail(id + "@demo.smartlect.local");
        session.setNickName("Smartlect用户" + userIndex);
        return getSuccessResponseVO(Map.of("userId", id, "addressId", "SD" + id,
                "token", redis.saveTokenUserInfo(session)));
    }

    private static String userId(int index) {
        if (index < 0 || index >= 100) throw new BusinessException("模拟用户编号必须在0到99之间");
        return String.valueOf(9100000000L + index);
    }
}
