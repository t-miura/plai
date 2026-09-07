/**
 * @file radio_tx_hook.h
 * @brief Abstract radio transmit lifecycle hook interface
 */

#pragma once

#include <stdint.h>
#include <stdbool.h>

namespace HAL
{
    class RadioInterface;
}

namespace Mesh
{
    struct QueuedPacket;

    /**
     * @brief Radio transmit lifecycle hook for regulatory compliance and transmission policies.
     */
    class RadioTxHook
    {
    public:
        enum PreTxAction
        {
            PRETX_SEND,  ///< Transmit permitted immediately
            PRETX_DEFER, ///< Defer transmission (e.g. mandatory pause or channel busy)
            PRETX_DROP   ///< Drop packet (e.g. airtime exceeds regulatory limit)
        };

        virtual ~RadioTxHook() = default;

        /**
         * @brief Called before transmission to check regulatory and channel policies.
         * @param iface Pointer to radio driver
         * @param p Pointer to the packet at head of TX queue (or nullptr)
         * @param estimated_airtime_ms Estimated airtime in milliseconds
         * @param defer_ms Output parameter for required defer/backoff delay in ms if PRETX_DEFER
         * @return PRETX_SEND, PRETX_DEFER, or PRETX_DROP
         */
        virtual PreTxAction beforeTransmit(HAL::RadioInterface* iface,
                                           const QueuedPacket* p,
                                           uint32_t estimated_airtime_ms,
                                           uint32_t& defer_ms)
        {
            defer_ms = 0;
            return PRETX_SEND;
        }

        /**
         * @brief Called after a packet was successfully transmitted over RF.
         * @param iface Pointer to radio driver
         * @param p Pointer to transmitted packet (or nullptr)
         */
        virtual void postTransmit(HAL::RadioInterface* iface, const QueuedPacket* p) {}

        /**
         * @brief Called when a packet was dropped, aborted, or released.
         * @param iface Pointer to radio driver
         * @param p Pointer to released packet (or nullptr)
         */
        virtual void packetReleased(HAL::RadioInterface* iface, const QueuedPacket* p) {}
    };

} // namespace Mesh
