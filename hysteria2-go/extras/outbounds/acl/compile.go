package acl

import (
	"fmt"
	"net"
	"strconv"
	"strings"

	lru "github.com/hashicorp/golang-lru/v2"
	"github.com/oschwald/geoip2-golang"
)

type Protocol int

const (
	ProtocolBoth Protocol = iota
	ProtocolTCP
	ProtocolUDP
)

type Outbound interface {
	any
}

type HostInfo struct {
	Name string
	IPv4 net.IP
	IPv6 net.IP
}

func (h HostInfo) String() string {
	return fmt.Sprintf("%s|%s|%s", h.Name, h.IPv4, h.IPv6)
}

type CompiledRuleSet[O Outbound] interface {
	Match(host HostInfo, proto Protocol, port uint16) (O, net.IP)
}

type compiledRule[O Outbound] struct {
	Outbound      O
	HostMatcher   hostMatcher
	Protocol      Protocol
	Port          uint16
	HijackAddress net.IP
}

func (r *compiledRule[O]) Match(host HostInfo, proto Protocol, port uint16) bool {
	if r.Protocol != ProtocolBoth && r.Protocol != proto {
		return false
	}
	if r.Port != 0 && r.Port != port {
		return false
	}
	return r.HostMatcher.Match(host)
}

type matchResult[O Outbound] struct {
	Outbound      O
	HijackAddress net.IP
}

type compiledRuleSetImpl[O Outbound] struct {
	Rules []compiledRule[O]
	Cache *lru.Cache[string, matchResult[O]] // key: HostInfo.String()
}

func (s *compiledRuleSetImpl[O]) Match(host HostInfo, proto Protocol, port uint16) (O, net.IP) {
	host.Name = strings.ToLower(host.Name) // Normalize host name to lower case
	key := host.String()
	if result, ok := s.Cache.Get(key); ok {
		return result.Outbound, result.HijackAddress
	}
	for _, rule := range s.Rules {
		if rule.Match(host, proto, port) {
			result := matchResult[O]{rule.Outbound, rule.HijackAddress}
			s.Cache.Add(key, result)
			return result.Outbound, result.HijackAddress
		}
	}
	// No match should also be cached
	var zero O
	s.Cache.Add(key, matchResult[O]{zero, nil})
	return zero, nil
}

type CompilationError struct {
	LineNum int
	Message string
}

func (e *CompilationError) Error() string {
	return fmt.Sprintf("error at line %d: %s", e.LineNum, e.Message)
}

// Compile compiles TextRules into a CompiledRuleSet.
// Names in the outbounds map MUST be in all lower case.
// geoipFunc is a function that returns the GeoIP database needed by the GeoIP matcher.
// It will be called every time a GeoIP matcher is used during compilation, but won't
// be called if there is no GeoIP rule. We use a function here so that database loading
// is on-demand (only required if used by rules).
func Compile[O Outbound](rules []TextRule, outbounds map[string]O,
	cacheSize int, geoipFunc func() *geoip2.Reader,
) (CompiledRuleSet[O], error) {
	compiledRules := make([]compiledRule[O], len(rules))
	for i, rule := range rules {
		outbound, ok := outbounds[strings.ToLower(rule.Outbound)]
		if !ok {
			return nil, &CompilationError{rule.LineNum, fmt.Sprintf("outbound %s not found", rule.Outbound)}
		}
		hm, errStr := compileHostMatcher(rule.Address, geoipFunc)
		if errStr != "" {
			return nil, &CompilationError{rule.LineNum, errStr}
		}
		proto, port, ok := parseProtoPort(rule.ProtoPort)
		if !ok {
			return nil, &CompilationError{rule.LineNum, fmt.Sprintf("invalid protocol/port: %s", rule.ProtoPort)}
		}
		var hijackAddress net.IP
		if rule.HijackAddress != "" {
			hijackAddress = net.ParseIP(rule.HijackAddress)
			if hijackAddress == nil {
				return nil, &CompilationError{rule.LineNum, fmt.Sprintf("invalid hijack address (must be an IP address): %s", rule.HijackAddress)}
			}
		}
		compiledRules[i] = compiledRule[O]{outbound, hm, proto, port, hijackAddress}
	}
	cache, err := lru.New[string, matchResult[O]](cacheSize)
	if err != nil {
		return nil, err
	}
	return &compiledRuleSetImpl[O]{compiledRules, cache}, nil
}

// parseProtoPort parses the protocol and port from a protoPort string.
// protoPort must be in one of the following formats:
//
//	proto/port
//	proto/*
//	proto
//	*/port
//	*/*
//	*
//	[empty] (same as *)
//
// proto must be either "tcp" or "udp", case-insensitive.
func parseProtoPort(protoPort string) (Protocol, uint16, bool) {
	protoPort = strings.ToLower(protoPort)
	if protoPort == "" || protoPort == "*" || protoPort == "*/*" {
		return ProtocolBoth, 0, true
	}
	parts := strings.SplitN(protoPort, "/", 2)
	if len(parts) == 1 {
		// No port, only protocol
		switch parts[0] {
		case "tcp":
			return ProtocolTCP, 0, true
		case "udp":
			return ProtocolUDP, 0, true
		default:
			return ProtocolBoth, 0, false
		}
	} else {
		// Both protocol and port
		var proto Protocol
		var port uint16
		switch parts[0] {
		case "tcp":
			proto = ProtocolTCP
		case "udp":
			proto = ProtocolUDP
		case "*":
			proto = ProtocolBoth
		default:
			return ProtocolBoth, 0, false
		}
		if parts[1] != "*" {
			p64, err := strconv.ParseUint(parts[1], 10, 16)
			if err != nil {
				return ProtocolBoth, 0, false
			}
			port = uint16(p64)
		}
		return proto, port, true
	}
}

func compileHostMatcher(addr string, geoipFunc func() *geoip2.Reader) (hostMatcher, string) {
	addr = strings.ToLower(addr) // Normalize to lower case
	if addr == "*" || addr == "all" {
		// Match all hosts
		return &allMatcher{}, ""
	}
	if strings.HasPrefix(addr, "geoip:") {
		// GeoIP matcher
		country := strings.ToUpper(addr[6:])
		if len(country) != 2 {
			return nil, fmt.Sprintf("invalid country code: %s", country)
		}
		db := geoipFunc()
		if db == nil {
			return nil, "failed to load GeoIP database"
		}
		return &geoipMatcher{db, country}, ""
	}
	if strings.Contains(addr, "/") {
		// CIDR matcher
		_, ipnet, err := net.ParseCIDR(addr)
		if err != nil {
			return nil, fmt.Sprintf("invalid CIDR address: %s", addr)
		}
		return &cidrMatcher{ipnet}, ""
	}
	if ip := net.ParseIP(addr); ip != nil {
		// Single IP matcher
		return &ipMatcher{ip}, ""
	}
	if strings.Contains(addr, "*") {
		// Wildcard domain matcher
		return &domainMatcher{
			Pattern:  addr,
			Wildcard: true,
		}, ""
	}
	// Nothing else matched, treat it as a non-wildcard domain
	return &domainMatcher{
		Pattern:  addr,
		Wildcard: false,
	}, ""
}
