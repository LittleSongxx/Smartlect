-- Per-value gallery backfill (layer on top of 02_catalog_seed.sql, applied by install_catalog.py).
-- The catalog mirror saved the same image bytes under different random names for the
-- product gallery vs the property cover, so string-based linkage never matched.
-- Each cover-carrying property value gets property_gallery = the gallery filenames whose
-- content (sha256) equals its card. Unmatched values stay empty and fall back to the
-- product-level cover. Generated from run/uploads/file content hashes; idempotent UPDATEs.

UPDATE product_property_value SET property_gallery = '2026-06/Djyjtfe0oRVYaDeIZvCm7M5x71PPsG.jpg' WHERE product_id = '622491960431656' AND property_value_id = '17819421246570'; -- 【弹力超软系列】趴姿小猪B-BO
UPDATE product_property_value SET property_gallery = '2026-06/OiLb7On6jv1SrU3Fr84FdXm9mo2PlA.jpg' WHERE product_id = '549376645121601' AND property_value_id = '17819397993284'; -- FG800 沙暴渐变-41英寸原声款
UPDATE product_property_value SET property_gallery = '2026-06/GfFtpUUWjBJ4vupGyuBCSMek7jLj7G.jpg' WHERE product_id = '303019597302892' AND property_value_id = '17819385819633'; -- 可乐*12+雪碧*8+芬达*4 330ml*24
UPDATE product_property_value SET property_gallery = '2026-06/rHg6EjhnJbnJBCwHC2AZ86w0JjL8kP.jpg' WHERE product_id = '065293686460191' AND property_value_id = '17819384293251'; -- 厚烧海苔分享装 385g*1袋
UPDATE product_property_value SET property_gallery = '2026-06/uBhA4dgu65Lo61y15ZzqviWSbrdMwg.jpg' WHERE product_id = '748346463863251' AND property_value_id = '17819380469563'; -- 铃铛猫+置物架+相框+小摆件
UPDATE product_property_value SET property_gallery = '2026-06/4MsbQS6FxvnI5LypKWnY9gwTqbc5zC.jpg' WHERE product_id = '100766326868880' AND property_value_id = '17819371910994'; -- 邂逅柔情淡香水50ml+双效持色唇釉174号
UPDATE product_property_value SET property_gallery = '2026-06/6mwPYeiO7ugtMUH6UO02uWyNY30Y4R.jpg' WHERE product_id = '650980987345712' AND property_value_id = '17818899129391'; -- 超值单主机
UPDATE product_property_value SET property_gallery = '2026-06/hz2G9r5DxdUEKQKEHiIHM4M9aObj1v.jpg' WHERE product_id = '650980987345712' AND property_value_id = '1781889979475'; -- 主机+27英寸显示器
UPDATE product_property_value SET property_gallery = '2026-06/SxUHBfpEffG8Hx89vvqFCIMr9yc0cF.png' WHERE product_id = '895150981058759' AND property_value_id = '1780554968348'; -- 银色
UPDATE product_property_value SET property_gallery = '2026-06/E4YrHMEHPuTwPpN3MLtAuinOclQfZf.png' WHERE product_id = '869004898763662' AND property_value_id = '1780490771139'; -- 14寸 M5芯片
UPDATE product_property_value SET property_gallery = '2026-06/E4YrHMEHPuTwPpN3MLtAuinOclQfZf.png' WHERE product_id = '869004898763662' AND property_value_id = '1780490923890'; -- 16寸 M5Pro芯片
UPDATE product_property_value SET property_gallery = '2026-06/6mT3DHcMK85AuArxMU62usPoRqC87M.png' WHERE product_id = '995230446006541' AND property_value_id = '1780489902527'; -- 白色
UPDATE product_property_value SET property_gallery = '202601/mATTdbHRVwMZgX8TwM2H5r3G55mAH8_thumbnail.png' WHERE product_id = '763086281772264' AND property_value_id = '1768050433492'; -- 【星星+月亮】闺蜜两条装
UPDATE product_property_value SET property_gallery = '202601/Es2Me5UbE9voEk0LJ5hv2cgbPXgB0l_thumbnail.jpg' WHERE product_id = '422543322296606' AND property_value_id = '1768048722327'; -- 蓝色
UPDATE product_property_value SET property_gallery = '202601/Uj6JdSIBYdZ2XKnp3mZDChMQHY7Kb9_thumbnail.jpg' WHERE product_id = '422543322296606' AND property_value_id = '1768048730485'; -- 绿色
UPDATE product_property_value SET property_gallery = '202601/KfF11QY8Fnr1J54e2I3bYH4clRB7XP_thumbnail.jpg' WHERE product_id = '422543322296606' AND property_value_id = '1768048730829'; -- 粉色
UPDATE product_property_value SET property_gallery = '202601/X5dQaMUMQ2p4b86LViJBdvkrjuZ0a5_thumbnail.jpg' WHERE product_id = '422543322296606' AND property_value_id = '1768048731301'; -- 白色
UPDATE product_property_value SET property_gallery = '202601/FIGbBuGwy3ut39zc85oTcqCsDFxqzi_thumbnail.png' WHERE product_id = '438316828084252' AND property_value_id = '1768052963764'; -- 整箱10包
UPDATE product_property_value SET property_gallery = '202601/FIGbBuGwy3ut39zc85oTcqCsDFxqzi_thumbnail.png' WHERE product_id = '438316828084252' AND property_value_id = '1768053085531'; -- 整箱30包
UPDATE product_property_value SET property_gallery = '202601/pCs23yyJQRaW6Auyj3GYh8UsPM7EuL_thumbnail.jpg' WHERE product_id = '864824304719236' AND property_value_id = '1768049124430'; -- 棕色
UPDATE product_property_value SET property_gallery = '202601/iefsqE9hoZuWkfMddNVcuf6f1mYnik_thumbnail.jpg' WHERE product_id = '864824304719236' AND property_value_id = '1768049128413'; -- 黑色
UPDATE product_property_value SET property_gallery = '2026-06/r9L058UAchM4M4kSx75wmdEI1sgoK8.jpg' WHERE product_id = '116420922896782' AND property_value_id = '17819414067073'; -- 日韩系统班
UPDATE product_property_value SET property_gallery = '2026-06/PlcVWlveNOJ5RM9R0g2h3bVw0wpTMW.jpg' WHERE product_id = '587742827032945' AND property_value_id = '17819408259360'; -- 红色
UPDATE product_property_value SET property_gallery = '2026-06/2rMFCZkhfEk5rVUGBOgAYcx7G6pEGl.jpg' WHERE product_id = '587742827032945' AND property_value_id = '1781940882354'; -- 绿色
UPDATE product_property_value SET property_gallery = '2026-06/MGzI6tMytQZly4G8OEg4bCM3PiIqP2.jpg' WHERE product_id = '088573992437392' AND property_value_id = '17819404064233'; -- 军械员工具箱 铝合金(京仓发货)
UPDATE product_property_value SET property_gallery = '2026-06/vDHfBXY7MvCDB9efOWoBzNoSdf2TqV.jpg' WHERE product_id = '435499775288057' AND property_value_id = '17819401443463'; -- 古刹檀香丨进口香料丨全车飘香
UPDATE product_property_value SET property_gallery = '2026-06/y5ZgB84vp8hKIZcJeTLaD35lS4XFE2.jpg' WHERE product_id = '627057993813554' AND property_value_id = '17819399758783'; -- 蔚来ES8六座（26款）TPE脚垫+银河抗污毯
UPDATE product_property_value SET property_gallery = '2026-06/3ucYUeIwOprUl6YFAAnS1CIG5pLSMV.jpg' WHERE product_id = '484914171487881' AND property_value_id = '17819395475063'; -- 行业【第一】1800mAh+变速压感灯
UPDATE product_property_value SET property_gallery = '2026-06/Vg6XutdF4eeJ3WaWIDTnyfpKVN5LV4.jpg' WHERE product_id = '293985085089344' AND property_value_id = '17819393652824'; -- 灰黑色
UPDATE product_property_value SET property_gallery = '2026-06/zj6WcId2vYSJDLwPWHcMDJhGQnaCWQ.jpg' WHERE product_id = '583435458113015' AND property_value_id = '17819391724073'; -- 红楼梦
UPDATE product_property_value SET property_gallery = '2026-06/CF3jlJfL9w4v3XlLZ9LoZRwih3BjnB.jpg' WHERE product_id = '485810554704298' AND property_value_id = '17819389587754'; -- 致长辈-福罐礼盒显心意 250g*1盒
UPDATE product_property_value SET property_gallery = '2026-06/5RiYRCS0mzs735otaxv5IV37xd05Ls.jpg' WHERE product_id = '327158568449097' AND property_value_id = '17819387631394'; -- 【性价比Plus】常用调料12件套
UPDATE product_property_value SET property_gallery = '2026-06/U7LZN7XdQJXUuWtHB51RT7FHQpadPR.jpg' WHERE product_id = '578084699484498' AND property_value_id = '17819382380913'; -- 卡夹款5卡6钩
UPDATE product_property_value SET property_gallery = '2026-06/c6anMRV9cJFlE1oRGJ55607kGDSE6C.jpg' WHERE product_id = '694835806434643' AND property_value_id = '17819374367904'; -- 【店铺主推】金枝玉叶68头
UPDATE product_property_value SET property_gallery = '2026-06/URkRvHeRcSICJ82g80DmDZaf1CPRNT.jpg' WHERE product_id = '467794132963439' AND property_value_id = '17819369574512'; -- 淡焦黄
UPDATE product_property_value SET property_gallery = '2026-06/TRC8jIAgNSclIhpMWHnWOW5yDquqKv.jpg' WHERE product_id = '811128851953351' AND property_value_id = '17819366864734'; -- 第4代丨小蜜罐滋润霜60ml+30ml*2|到手120ml
UPDATE product_property_value SET property_gallery = '2026-06/rMHi7MLPENovo8m9mkQTgHklfXorFS.jpg' WHERE product_id = '270126564877983' AND property_value_id = '17819363169580'; -- 黑色大号【鞋仓+干湿分离】
UPDATE product_property_value SET property_gallery = '2026-06/EjIPM5KCOC0lIq2IjJhgiGeF5K01DB.jpg' WHERE product_id = '993921843864063' AND property_value_id = '17819360956630'; -- 玄青黑
UPDATE product_property_value SET property_gallery = '2026-06/9oKyzaQjpF5YHtvewIWeDT5hHWmzel.jpg' WHERE product_id = '053997047858558' AND property_value_id = '17818909121210'; -- 星夜银
UPDATE product_property_value SET property_gallery = '2026-06/Cyg6otkhTTvP94QpCRjzfb3QDe8LH8.jpg' WHERE product_id = '053997047858558' AND property_value_id = '1781890936994'; -- 冷夜蓝
UPDATE product_property_value SET property_gallery = '2026-06/9hIWG2qJFGVjpYLpeefUfbZYyocdXR.jpg' WHERE product_id = '053997047858558' AND property_value_id = '1781890946377'; -- 浅玫粉
UPDATE product_property_value SET property_gallery = '2026-06/bw1C1fxaBkduUaehu3pqx8F2FnnupR.jpg' WHERE product_id = '301841010226518' AND property_value_id = '17818895089021'; -- 单主机
UPDATE product_property_value SET property_gallery = '2026-06/VLSCvzcEJvs6tz46Pg2mMLJlKt03MQ.jpg' WHERE product_id = '301841010226518' AND property_value_id = '1781889560413'; -- 27寸显示器
UPDATE product_property_value SET property_gallery = '202601/LAiipAPzyFzNCbFvWsKDaD1w68MdJd_thumbnail.png' WHERE product_id = '298286497857602' AND property_value_id = '1768126212913'; -- #01乌木甜茶 ⭐【HOT】豆蔻粉红棕
UPDATE product_property_value SET property_gallery = '202601/pUwyKfd2B813LuFGKyp0xAqHKPkWfY_thumbnail.png' WHERE product_id = '843304724668395' AND property_value_id = '1768052450716'; -- 不累的工
UPDATE product_property_value SET property_gallery = '202601/aD81Jp6lpqOp3loRPTqS9ehyzt7DaW_thumbnail.png' WHERE product_id = '843304724668395' AND property_value_id = '1768052488467'; -- 舒服的假

-- Samsung Z Fold6: product cover carried byte-duplicate images (5 slots, 3 distinct);
-- keep one per color so the gallery count matches the 3 color SKUs.
UPDATE product_info SET cover = '2026-06/9hIWG2qJFGVjpYLpeefUfbZYyocdXR.jpg,2026-06/Cyg6otkhTTvP94QpCRjzfb3QDe8LH8.jpg,2026-06/9oKyzaQjpF5YHtvewIWeDT5hHWmzel.jpg' WHERE product_id = '053997047858558';
