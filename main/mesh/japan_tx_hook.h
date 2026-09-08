/**
 * @file japan_tx_hook.h
 * @brief ARIB STD-T108 regulatory transmit hook for Japan (JP) region
 */

#pragma once

#include "radio_tx_hook.h"
#include "meshtastic/config.pb.h"
#include <algorithm>

namespace Mesh
{

    /**
     * @brief RadioTxHook enforcing ARIB STD-T108 compliance for Japan (JP) region:
     *  1. Continuous RSSI carrier sensing for >= 5 ms at -80 dBm threshold before transmission,
     *     with exponential backoff (250 ms - 4000 ms) when busy.
     *  2. Minimum 50 ms inter-transmission pause between consecutive transmissions.
     *  3. Maximum 4000 ms single-burst airtime limit.
     *  4. Complete isolation for non-JP regions (zero delay, zero RSSI gating).
     */
    class JapanTxHook : public RadioTxHook
    {
    public:
        static constexpr int16_t CARRIER_SENSE_THRESHOLD_DBM = -80;
        static constexpr uint32_t CARRIER_SENSE_TIME_MS = 5;
        static constexpr uint32_t INTER_TX_PAUSE_MS = 50;
        static constexpr uint32_t MAX_TX_DURATION_MS = 4000;
        static constexpr uint32_t BACKOFF_BASE_MS = 250;
        static constexpr uint32_t BACKOFF_MAX_MS = 4000;
        static constexpr int16_t RSSI_UNAVAILABLE = 0;
        // Lower bound accommodates SX126x (-141 dBm), SX127x (-164 dBm HF offset), and LR11x0, above driver/SPI errors (< -192).
        static constexpr int16_t RSSI_VALID_MIN = -192;
        static constexpr int16_t RSSI_INVALID_DRIVER_ERROR = -706;

        JapanTxHook();
        ~JapanTxHook() override;

        PreTxAction beforeTransmit(HAL::RadioInterface* iface,
                                   const QueuedPacket* p,
                                   uint32_t estimated_airtime_ms,
                                   uint32_t& defer_ms) override;
        void postTransmit(HAL::RadioInterface* iface, const QueuedPacket* p) override;
        void packetReleased(HAL::RadioInterface* iface, const QueuedPacket* p) override;

        static uint32_t getTxPauseDurationMs();
        static uint32_t getTxPauseDurationMs(meshtastic_Config_LoRaConfig_RegionCode region);
        static uint32_t getMaxTxDurationMs();
        static uint32_t getMaxTxDurationMs(meshtastic_Config_LoRaConfig_RegionCode region);
        static bool isJapanRegion();
        static bool isJapanRegion(meshtastic_Config_LoRaConfig_RegionCode region);
        static uint32_t computeBackoffMs(uint32_t count);

        // Valid RSSI must be strictly negative (< 0 rejects 0 fallback and positive saturation) and >= -192 dBm.
        static bool isValidRssi(int16_t rssi) { return rssi < 0 && rssi >= RSSI_VALID_MIN; }

        bool performCarrierSense(HAL::RadioInterface* iface);

        bool isJapan() const { return _is_japan; }
        void setJapanRegion(bool is_jp) { _is_japan = is_jp; }

        uint32_t getLastTxEndTime() const { return _lastTxEndTime; }
        void setLastTxEndTime(uint32_t t) { _lastTxEndTime = t; }
        uint32_t getBusyCount() const { return _busyCount; }
        void resetBusyCount() { _busyCount = 0; }
        void reset()
        {
            _lastTxEndTime = 0;
            _busyCount = 0;
        }

    private:
        uint32_t _lastTxEndTime = 0;
        uint32_t _busyCount = 0;
        bool _is_japan = false;
    };

    extern JapanTxHook* japanTxHook;
    void setGlobalJapanTxHook(JapanTxHook* hook);
    void initJapanTxHook(JapanTxHook* hook);
    uint32_t getTxPauseDurationMs();

} // namespace Mesh
