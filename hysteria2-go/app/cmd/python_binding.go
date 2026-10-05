package cmd

import (
	"bytes"
	"os"
	"os/signal"
	"syscall"

	"github.com/apernet/hysteria/app/v2/internal/tun"
	"github.com/apernet/hysteria/app/v2/internal/utils"
	"github.com/apernet/hysteria/core/v2/client"
	"github.com/spf13/viper"
	"go.uber.org/zap"
	"go.uber.org/zap/zapcore"
)

func initPythonBindingLogger() {
	consoleEncoder := logFormatMap["console"]
	consoleEncoder.EncodeLevel = zapcore.CapitalLevelEncoder
	logFormatMap["console"] = consoleEncoder
	initLogger()
}

// StartFromJSON starts a Hysteria client from an in-memory JSON configuration.
func StartFromJSON(jsonConfig string) {
	initPythonBindingLogger()
	logger.Info("client mode")

	configReader := viper.New()
	configReader.SetConfigType("json")
	if err := configReader.ReadConfig(bytes.NewBufferString(jsonConfig)); err != nil {
		logger.Error("failed to read client config", zap.Error(err))
		// Xray-core: Configuration error
		os.Exit(23)
	}
	var config clientConfig
	if err := configReader.Unmarshal(&config); err != nil {
		logger.Error("failed to parse client config", zap.Error(err))
		// Xray-core: Configuration error
		os.Exit(23)
	}

	c, err := client.NewReconnectableClient(
		config.Config,
		func(c client.Client, info *client.HandshakeInfo, count int) {
			connectLog(info, count)
			// On the client side, we start checking for updates after we successfully connect
			// to the server, which, depending on whether lazy mode is enabled, may or may not
			// be immediately after the client starts. We don't want the update check request
			// to interfere with the lazy mode option.
			//if count == 1 && !disableUpdateCheck {
			//	go runCheckUpdateClient(c)
			//}
		}, config.Lazy,
	)
	if err != nil {
		logger.Fatal("failed to initialize client", zap.Error(err))
	}
	defer c.Close()

	uri := config.URI()
	if showQR {
		logger.Warn("--qr flag is deprecated and will be removed in future release, " +
			"please use `share` subcommand to generate share URI and QR code")
		logger.Info("use this URI to share your server", zap.String("uri", uri))
		utils.PrintQR(uri)
	}

	var runner clientModeRunner
	if config.SOCKS5 != nil {
		runner.Add("SOCKS5 server", func() error {
			return clientSOCKS5(*config.SOCKS5, c)
		})
	}
	if config.HTTP != nil {
		runner.Add("HTTP proxy server", func() error {
			return clientHTTP(*config.HTTP, c)
		})
	}
	if len(config.TCPForwarding) > 0 {
		runner.Add("TCP forwarding", func() error {
			return clientTCPForwarding(config.TCPForwarding, c)
		})
	}
	if len(config.UDPForwarding) > 0 {
		runner.Add("UDP forwarding", func() error {
			return clientUDPForwarding(config.UDPForwarding, c)
		})
	}
	if config.TCPTProxy != nil {
		runner.Add("TCP transparent proxy", func() error {
			return clientTCPTProxy(*config.TCPTProxy, c)
		})
	}
	if config.UDPTProxy != nil {
		runner.Add("UDP transparent proxy", func() error {
			return clientUDPTProxy(*config.UDPTProxy, c)
		})
	}
	if config.TCPRedirect != nil {
		runner.Add("TCP redirect", func() error {
			return clientTCPRedirect(*config.TCPRedirect, c)
		})
	}
	var tunServer *tun.Server
	if config.TUN != nil {
		tunServer, err = newTUNServer(*config.TUN, c)
		if err != nil {
			_ = c.Close()
			logger.Fatal("failed to load client config", zap.Error(err))
		}
		// The TUN adds routes and rules to the system, remove them on exit.
		defer tunServer.Close()
		runner.Add("TUN", func() error {
			logger.Info("TUN listening", zap.String("interface", config.TUN.Name))
			return tunServer.Serve()
		})
	}

	signalChan := make(chan os.Signal, 1)
	signal.Notify(signalChan, os.Interrupt, syscall.SIGTERM)
	defer signal.Stop(signalChan)

	runnerChan := make(chan clientModeRunnerResult, 1)
	go func() {
		runnerChan <- runner.Run()
	}()

	select {
	case <-signalChan:
		logger.Info("received signal, shutting down gracefully")
	case result := <-runnerChan:
		if result.OK {
			logger.Info(result.Msg)
		} else {
			// Fatal exits without running deferred cleanup.
			if tunServer != nil {
				_ = tunServer.Close()
			}
			_ = c.Close()
			if result.Err != nil {
				logger.Fatal(result.Msg, zap.Error(result.Err))
			} else {
				logger.Fatal(result.Msg)
			}
		}
	}
}
