/**
 * @file japan_tx_hook.cpp
 * @brief ARIB STD-T108 regulatory transmit hook implementation for Japan (JP) region
 */

#include "mesh_service.h"
#include "japan_tx_hook.h"
#include "hal/radio/radio_interface.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_random.h"
#include "esp_rom_sys.h"
#include "common_define.h"
#include <algorithm>

static const char* TAG = "JapanTxHook";

namespace Mesh
{

    JapanTxHook* japanTxHook = nullptr;

    void setGlobalJapanTxHook(JapanTxHook* hook)
    {
        japanTxHook = hook;
    }

    void initJapanTxHook(JapanTxHook* hook)
    {
        setGlobalJapanTxHook(hook);
    }

    uint32_t getTxPauseDurationMs()
    {
        return JapanTxHook::getTxPauseDurationMs();
    }

    JapanTxHook::JapanTxHook() : RadioTxHook()
    {
        // Side-effect-free constructor (Rule 6 invariant)
    }

    JapanTxHook::~JapanTxHook()
    {
        if (japanTxHook == this)
            japanTxHook = nullptr;
    }

    bool JapanTxHook::isJapanRegion()
    {
        if (japanTxHook)
            return japanTxHook->isJapan();
        MeshService* svc = MeshService::getInstance();
        if (svc && svc->getMyRegion())
            return svc->getMyRegion()->code == meshtastic_Config_LoRaConfig_RegionCode_JP;
        return false;
    }

    bool JapanTxHook::isJapanRegion(meshtastic_Config_LoRaConfig_RegionCode region)
    {
        return region == meshtastic_Config_LoRaConfig_RegionCode_JP;
    }

    uint32_t JapanTxHook::getTxPauseDurationMs()
    {
        return isJapanRegion() ? INTER_TX_PAUSE_MS : 0;
    }

    uint32_t JapanTxHook::getTxPauseDurationMs(meshtastic_Config_LoRaConfig_RegionCode region)
    {
        return isJapanRegion(region) ? INTER_TX_PAUSE_MS : 0;
    }

    uint32_t JapanTxHook::getMaxTxDurationMs()
    {
        return isJapanRegion() ? MAX_TX_DURATION_MS : UINT32_MAX;
    }

    uint32_t JapanTxHook::getMaxTxDurationMs(meshtastic_Config_LoRaConfig_RegionCode region)
    {
        return isJapanRegion(region) ? MAX_TX_DURATION_MS : UINT32_MAX;
    }

    uint32_t JapanTxHook::computeBackoffMs(uint32_t count)
    {
        if (count == 0)
            return 0;
        uint32_t shift = (count > 8) ? 8 : count;
        uint32_t maxBackoff = std::min((uint32_t)(BACKOFF_BASE_MS * (1u << shift)), BACKOFF_MAX_MS);
        uint32_t minBackoff = maxBackoff / 2;
        return minBackoff + (esp_random() % (maxBackoff - minBackoff + 1));
    }

    bool JapanTxHook::performCarrierSense(HAL::RadioInterface* iface)
    {
        if (!iface)
            return true;

        // Ensure radio is in RX mode before reading instantaneous RSSI
        if (iface->getMode() != HAL::RadioMode::RX)
        {
            iface->startReceive(0);
        }

        const int64_t start_us = esp_timer_get_time();
        const int64_t target_us = (int64_t)CARRIER_SENSE_TIME_MS * 1000;

        while ((esp_timer_get_time() - start_us) < target_us)
        {
            int16_t rssi = iface->getCurrentRSSI();
            if (isValidRssi(rssi) && rssi >= CARRIER_SENSE_THRESHOLD_DBM)
            {
                ESP_LOGI(TAG, "JP LBT: carrier sensed during 5ms window (RSSI %d dBm >= %d dBm)",
                         rssi, CARRIER_SENSE_THRESHOLD_DBM);
                return false;
            }
            esp_rom_delay_us(250);
        }

        int16_t finalRssi = iface->getCurrentRSSI();
        if (isValidRssi(finalRssi) && finalRssi >= CARRIER_SENSE_THRESHOLD_DBM)
        {
            ESP_LOGI(TAG, "JP LBT: carrier sensed at end of 5ms window (RSSI %d dBm >= %d dBm)",
                     finalRssi, CARRIER_SENSE_THRESHOLD_DBM);
            return false;
        }

        return true;
    }

    RadioTxHook::PreTxAction JapanTxHook::beforeTransmit(HAL::RadioInterface* iface,
                                                         const QueuedPacket* p,
                                                         uint32_t estimated_airtime_ms,
                                                         uint32_t& defer_ms)
    {
        defer_ms = 0;
        if (!isJapan() || !p)
            return PRETX_SEND;

        // R2: Inter-Transmission Pause Duration Enforcement (>= 50ms)
        const uint32_t pauseMs = isJapan() ? INTER_TX_PAUSE_MS : 0;
        const uint32_t now = millis();
        if (_lastTxEndTime != 0 && (now - _lastTxEndTime < pauseMs))
        {
            defer_ms = pauseMs - (now - _lastTxEndTime);
            if (defer_ms == 0)
                defer_ms = 1;
            ESP_LOGI(TAG, "JP LBT: deferring packet for mandatory 50ms pause (remaining %lu ms)",
                     (unsigned long)defer_ms);
            return PRETX_DEFER;
        }

        // R1: Instantaneous RSSI Carrier Sensing (>= 5ms at -80 dBm)
        if (!performCarrierSense(iface))
        {
            _busyCount++;
            defer_ms = computeBackoffMs(_busyCount);
            if (defer_ms == 0)
                defer_ms = 1;
            ESP_LOGI(TAG, "JP LBT: channel busy (attempt %lu), backing off %lu ms",
                     (unsigned long)_busyCount, (unsigned long)defer_ms);
            return PRETX_DEFER;
        }

        _busyCount = 0;
        ESP_LOGI(TAG, "JP LBT: carrier sense clear (5ms window), transmit permitted");
        return PRETX_SEND;
    }

    void JapanTxHook::postTransmit(HAL::RadioInterface* iface, const QueuedPacket* p)
    {
        (void)iface;
        (void)p;
        if (!isJapan())
            return;
        resetBusyCount();
        _lastTxEndTime = millis();
        if (_lastTxEndTime == 0)
            _lastTxEndTime = 1;
    }

    void JapanTxHook::packetReleased(HAL::RadioInterface* iface, const QueuedPacket* p)
    {
        (void)iface;
        (void)p;
        resetBusyCount();
    }

} // namespace Mesh
