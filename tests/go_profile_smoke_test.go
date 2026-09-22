package device

import (
    "strings"
    "fmt"
    "net/netip"
    "github.com/amnezia-vpn/amneziawg-go/v3/conn/bindtest"
    "github.com/amnezia-vpn/amneziawg-go/v3/tun"
    "github.com/amnezia-vpn/amneziawg-go/v3/tun/tuntest"
    "testing"
)

// Synthetic keys and loopback only: never connect to the user's VPN server.
func TestRouterAWG31Profile(t *testing.T) {
    for _, sockets := range []bool{false, true} {
        name := "in-memory"
        if sockets { name = "loopback-udp" }
        t.Run(name, func(t *testing.T) {
            pair := genTestPair(t, sockets,
                "jc", "4", "jmin", "40", "jmax", "70",
                "s1", "15", "s2", "25", "s3", "24", "s4", "12",
                "h1", "123456-123500", "h2", "67543-67550",
                "h3", "123123-123200", "h4", "32345-32350",
                "header_protection_key", strings.Repeat("11", 32),
                "content_padding_addition", "10-100",
                "random_trailers", "true", "disable_cookies", "true",
            )
            pair.Send(t, Ping, nil)
            pair.Send(t, Pong, nil)
        })
    }
}

type observedTUN struct {
    tun.Device
    started chan int
}

func (d *observedTUN) Read(bufs [][]byte, sizes []int, offset int) (int, error) {
    d.started <- offset
    return d.Device.Read(bufs, sizes, offset)
}

// Force Read to capture old S4 before each configuration change.
func TestRouterS4ChangeWhileReadBlocked(t *testing.T) {
    configs, endpoints := genConfigs(t,
        "s1", "15", "s2", "25", "s3", "24", "s4", "25",
        "header_protection_key", strings.Repeat("22", 32))
    binds := bindtest.NewChannelBinds()
    var pair testPair
    var observed [2]*observedTUN
    for i := range pair {
        p := &pair[i]
        p.tun = tuntest.NewChannelTUN()
        p.ip = netip.AddrFrom4([4]byte{1, 0, 0, byte(i+1)})
        observed[i] = &observedTUN{Device:p.tun.TUN(), started:make(chan int, 8)}
        p.dev = NewDevice(observed[i], binds[i], NewLogger(LogLevelError, "regression"))
        t.Cleanup(p.dev.Close)
        <-observed[i].started
        if err := p.dev.IpcSet(configs[i]); err != nil { t.Fatal(err) }
        if err := p.dev.Up(); err != nil { t.Fatal(err) }
        endpoints[i^1] = fmt.Sprintf(endpoints[i^1], p.dev.net.port)
    }
    for i := range pair {
        if err := pair[i].dev.IpcSet(endpoints[i]); err != nil { t.Fatal(err) }
    }
    pair.Send(t, Ping, nil)
    pair.Send(t, Pong, nil)
    for _, padding := range []string{"12", "40"} {
        for i := range pair {
            <-observed[i].started
            if err := pair[i].dev.IpcSet(uapiCfg("s4", padding)); err != nil { t.Fatal(err) }
        }
        pair.Send(t, Ping, nil)
        pair.Send(t, Pong, nil)
    }
}
