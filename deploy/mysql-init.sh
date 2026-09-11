# Sourced by the official MySQL entrypoint on first initialization only.
for identity in app flyway nacos seata growth; do
  case "$identity" in
    app) secret="$SMARTLECT_MYSQL_PASSWORD" ;;
    flyway) secret="$SMARTLECT_FLYWAY_PASSWORD" ;;
    nacos) secret="$SMARTLECT_NACOS_MYSQL_PASSWORD" ;;
    seata) secret="$SMARTLECT_SEATA_MYSQL_PASSWORD" ;;
    growth) secret="$SMARTLECT_GROWTH_MYSQL_PASSWORD" ;;
  esac
  [[ "$secret" =~ ^[a-f0-9]{48}$ ]] || { echo 'Invalid generated Smartlect credential' >&2; exit 1; }
  docker_process_sql <<< "CREATE USER 'smartlect_${identity}'@'%' IDENTIFIED BY '${secret}';"
done
for domain in admin user product stock cart order pay coupon nacos seata growth; do
  docker_process_sql <<< "CREATE DATABASE smartlect_${domain} CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;"
  case "$domain" in
    nacos|seata|growth)
      docker_process_sql <<< "GRANT ALL ON smartlect_${domain}.* TO 'smartlect_${domain}'@'%';" ;;
    *)
      docker_process_sql <<< "GRANT SELECT, INSERT, UPDATE, DELETE ON smartlect_${domain}.* TO 'smartlect_app'@'%';"
      docker_process_sql <<< "GRANT ALL ON smartlect_${domain}.* TO 'smartlect_flyway'@'%';" ;;
  esac
done
unset identity secret domain
