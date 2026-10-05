import Request from "@/utils/Request"
const Api = {

    checkCode: "/account/checkCode",
    login: "/account/login",
    logout: "/account/logout",
    adminMe: "/account/me",

    sourcePath: "/admin-api/file/getResource?sourceName=",
    uploadImage: "/file/uploadImage",

    loadCategory: "/sysCategory/loadCategory",
    saveCategory: "/sysCategory/saveCategory",
    delCategory: "/sysCategory/delCategory",
    changeCategorySort: "/sysCategory/changeCategorySort",

    saveProductProperty: "/sysCategory/saveProductProperty",
    delProductProperty: "/sysCategory/delProductProperty",

    addProduct: "/productInfo/addProduct",
    updateProduct: "/productInfo/updateProduct",
    getProductInfo: "/productInfo/getProductInfo",
    loadProduct: "/productInfo/loadProduct",
    updateSkuStock: "/productInfo/updateSkuStock",
    updateProductStatus: "/productInfo/updateProductStatus",
    deleteProduct: "/productInfo/deleteProduct",
    commendProduct: "/productInfo/commendProduct",

    loadOrderStatus: "/order/loadOrderStatus",
    loadOrder: "/order/loadOrder",
    getLogistics: "/order/getLogistics",
    delivery: "/order/delivery",
    imageModerationLoadList: "/imageModeration/loadDataList",
    imageModerationGetByRecordId: "/imageModeration/getByRecordId",
    imageModerationHandleReview: "/imageModeration/handleReview",
    imageModerationGetTempBanInfo: "/imageModeration/getTempBanInfo",
    imageModerationUnbanUser: "/imageModeration/unbanUser",
    imageModerationCensorImage: "/imageModeration/censorImage",
    mqCompensationLogLoadList: "/mqCompensationLog/loadDataList",
    mqCompensationLogGetByLogId: "/mqCompensationLog/getByLogId",
    mqCompensationLogUpdateStatus: "/mqCompensationLog/updateStatus",
    mqCompensationLogReplay: "/mqCompensationLog/replay",

    loadUser: "/user/loadUser",
    changeStatus: "/user/changeStatus",

    saveSysSaveLogistics: "/setting/saveLogistics",
    getSysLogistics: "/setting/getLogistics",

    getTodayData: "/home/getTodayData",
    loadWeeklyStatisticsData: "/home/loadWeeklyStatisticsData",
    loadLessStockProduct: "/home/loadLessStockProduct",

    loadDiscountCoupon: "/discountCoupon/loadDiscountCoupon",
    saveDiscountCoupon: "/discountCoupon/saveDiscountCoupon",
    getDiscountCouponInfo: "/discountCoupon/getDiscountCouponInfo",
    updateDiscountCouponStatus: "/discountCoupon/updateDiscountCouponStatus",

    warmupRushStock: "/discountCoupon/warmupRushStock",
    reconcileRushStock: "/discountCoupon/reconcileRushStock",

    toolStatistics: "/tool/statistics",
    toolAddAllOrderToDelayQueue: "/tool/addAllOrderToDelayQueue",
    refundReviewLoadList: "/refundReview/loadDataList",
    refundReviewApprove: "/refundReview/approve",
    refundReviewReject: "/refundReview/reject",

    statisticsInfoLoadList: "/statisticsInfo/loadDataList",

    userAddressLoadList: "/userAddress/loadDataList",
    userAddressDelete: "/userAddress/deleteUserAddressByAddressId",
}

const uploadImage = async (file, createThumbnail = false) => {
    const { prepareImageForUpload } = await import('@/utils/imageUpload.js')
    const prepared = await prepareImageForUpload(file)
    const ext = prepared.type === 'image/png' ? 'png' : 'jpg'
    const uploadFile = new File(
        [prepared],
        file?.name ? file.name.replace(/\.\w+$/, `.${ext}`) : `image.${ext}`,
        { type: prepared.type || 'image/jpeg' }
    )
    let result = await Request({
        url: Api.uploadImage,
        params: {
            file: uploadFile,
            createThumbnail
        },
    })
    if (!result) {
        return;
    }
    return result.data;
}
export {
    Api,
    uploadImage
}
