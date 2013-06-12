
#ifndef SJINGLE_XMPPNETWORK_H_
#define SJINGLE_XMPPNETWORK_H_
#pragma once

#include <string>

#include "talk/xmpp/xmpptask.h"
#include "talk/xmpp/xmppengine.h"
#include "talk/xmpp/presencestatus.h"
#include "talk/xmpp/presencereceivetask.h"
#include "talk/xmpp/presenceouttask.h"
#include "talk/xmpp/xmppclient.h"
#include "talk/xmpp/xmppsocket.h"
#include "talk/xmpp/xmpppump.h"
#include "talk/base/sigslot.h"

namespace sjingle {

static const char kXmppPrefix[] = "svpn";
static const int kHeaderSize = 40;
static const int kIdSize = 18;

class SocialNetworkSenderInterface {
 public:
  // Slot for message callbacks
  sigslot::signal2<const std::string&, const std::string&> HandlePeer;

  virtual const std::string uid() = 0;
  virtual void SendToPeer(const std::string& uid, const std::string& sdp) = 0;

 protected:
  virtual ~SocialNetworkSenderInterface() {}
};

class SvpnTask
    : public SocialNetworkSenderInterface,
      public buzz::XmppTask {
 public:
  explicit SvpnTask(buzz::XmppClient* client)
      : XmppTask(client, buzz::XmppEngine::HL_SINGLE) {}

  // inherited from SocialSenderInterface
  virtual const std::string uid() { return GetClient()->jid().Str(); }

  virtual void SendToPeer(const std::string& uid, const std::string& data);

 protected:
  virtual int ProcessStart();
  virtual bool HandleStanza(const buzz::XmlElement* stanza);
};

class XmppNetwork 
    : public SocialNetworkSenderInterface,
      public sigslot::has_slots<> {
 public:
  explicit XmppNetwork() : state_(), xcs_(), online_(false){};

  // Slot for message callbacks
  sigslot::signal2<const std::string&, const std::string&> HandlePeer;

  void Login(std::string username, std::string password,
             std::string pcid, std::string host);

  // inherited from SocialSenderInterface
  virtual const std::string uid() { 
    if (online_) return state_->svpn_task->uid();
    else return "offline"; 
  }

  virtual void SendToPeer(const std::string& uid, const std::string& data) {
    state_->svpn_task->SendToPeer(uid, data);
  }

  virtual void set_status(const std::string& status) {
    status_.set_status(status);
  }

  struct XmppState {
    talk_base::scoped_ptr<buzz::XmppPump> pump;
    talk_base::scoped_ptr<buzz::XmppSocket> xmpp_socket;
    talk_base::scoped_ptr<buzz::PresenceReceiveTask> presence_receive;
    talk_base::scoped_ptr<buzz::PresenceOutTask> presence_out;
    talk_base::scoped_ptr<SvpnTask> svpn_task;
  };

 private:
  talk_base::scoped_ptr<XmppState> state_;
  buzz::XmppClientSettings xcs_;
  buzz::PresenceStatus status_;
  bool online_;

  void Connect();
  void OnSignOn();
  void OnStateChange(buzz::XmppEngine::State state);
  void OnPresenceMessage(const buzz::PresenceStatus &status);
  void OnCloseEvent(int error);

};

}  // namespace sjingle

#endif  // SJINGLE_XMPPNETWORK_H_
